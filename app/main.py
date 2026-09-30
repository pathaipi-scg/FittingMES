import hashlib
import json
from contextlib import closing
from uuid import uuid4
from pathlib import Path
from datetime import date, datetime, time
from urllib.parse import quote, urlencode
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse, PlainTextResponse
from starlette.background import BackgroundTask
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool
from app.lots import rows, day, read_lots, update_lot, insert_lot, next_running_no, reorder_lot

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.database import get_connection
from app.pis_config import PISConfig
from app.pis_client import PISClient, PISClientError
from app.usage import read_usage_context, save_usage
from app.prod_api import (read_prod_records, read_historical_plans, build_pis_date_preview,
                          field_mapping, lot_readiness, preview_readiness)
from app.production_pis_log import latest_states
from app.production_pis_send import FAILED, SUCCESS, UNKNOWN, send_ready_groups
from app.pis_send_log import audit_row, insert_audit_rows
from app.reject_api import (read_reject_records, reject_readiness, build_reject_preview,
                            build_output_details_query, parse_output_details_response,
                            summarize_output_details, build_change_status_preview)
from app.reject_pis_log import latest_states as latest_reject_states
from app.reject_pis_send import send_reject_single
from app.depallet import (read_context as read_depallet_context, read_reasons as read_depallet_reasons,
                          read_curing_lots, read_daily_work, save_depallet, save_depallet_batch,
                          reorder_depallet_run)
from app.products import FAMILIES, lot_prefix, read_products, read_mapping, confirm_mapping, selected_product, month_start
from app.production_data import read_production_data, save_production_data, calculate
from app.press_mc import (page_context as press_mc_context, add_press, update_press_name,
                          assign_line, remove_from_line, set_active, save_capabilities)
from app.mould import (page_context as mould_context, register_mould, update_mould_info,
                       send_to_recondition, return_from_recondition, set_mould_status)
from app.press_production import (build_press_production_context,
                                  undo_release_press_production,
                                  release_press_production,
                                  save_press_production as save_press_production_row)
from app.wet_reject import build_wet_reject_context, save_wet_reject, save_wet_reject_batch
from app.print_prod import read_print_prod_context
from app.browser_pdf import (PdfGenerationError, generate_print_prod_pdf,
                             finish_pdf_process)
from app.logger import (LoggerValidationError, read_logger_events,
                        read_logger_masters, save_logger_event)
from app.logger_page import (cause_suggestion, logger_form_input,
                             logger_page_context, normalize_form_selection)

app = FastAPI(title="FittingMES", version="0.1.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def logger_load_context(production_date, saved=False, error=None, form=None):
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        masters = read_logger_masters(cursor)
        events = read_logger_events(cursor, production_date)
    return logger_page_context(masters, production_date, logger_events=events, saved=saved,
                               error=error, form=form)


@app.get('/logger', response_class=HTMLResponse)
def logger_page(request: Request, production_date: date | None = None,
                saved: bool = False):
    production_date = production_date or date.today()
    status = 200
    try:
        context = logger_load_context(production_date, saved=saved)
    except ValueError as exc:
        context = dict(page_title='LOGGER', active_tab='logger',
                       production_date=production_date, error=str(exc), saved=False,
                       logger_events=[])
        status = 400
    except Exception:
        context = dict(page_title='LOGGER', active_tab='logger',
                       production_date=production_date,
                       error='Unable to load LOGGER data. Please retry.', saved=False,
                       logger_events=[])
        status = 503
    return templates.TemplateResponse(request=request, name='logger.html',
                                      context=context, status_code=status,
                                      headers={'Cache-Control': 'no-store'})


def save_logger_form(form):
    data, selection = logger_form_input(form)
    with closing(get_connection()) as conn:
        masters = read_logger_masters(conn.cursor())
        normalized = normalize_form_selection(selection, masters)
        data = data.__class__(
            **{**data.__dict__,
               'related_mc_id': normalized['related_mc_id'],
               'related_mc_instance_no': normalized['related_mc_instance_no'],
               'sub_mc_id': normalized['sub_mc_id'],
               'sub_mc_instance_no': normalized['sub_mc_instance_no']})
        save_logger_event(conn, data, masters)
    return data.production_date


@app.post('/logger/save', response_class=HTMLResponse)
async def save_logger_route(request: Request):
    form = await request.form()
    form_values = dict(form)
    try:
        production_date = await run_in_threadpool(save_logger_form, form_values)
        return RedirectResponse(f'/logger?production_date={production_date}&saved=true',
                                status_code=303)
    except LoggerValidationError as exc:
        try:
            selected_date = date.fromisoformat(str(form_values.get('production_date', '')))
        except ValueError:
            selected_date = date.today()
        try:
            context = await run_in_threadpool(
                logger_load_context, selected_date, False,
                f'{exc.code}: {exc}', form_values)
        except Exception:
            context = dict(page_title='LOGGER', active_tab='logger',
                           production_date=selected_date, error=str(exc),
                           saved=False, form=form_values, logger_events=[])
        return templates.TemplateResponse(request=request, name='logger.html',
                                          context=context, status_code=400,
                                          headers={'Cache-Control': 'no-store'})
    except ValueError as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({'error': 'Unable to save LOGGER entry. Please retry.'},
                            status_code=503)


def read_plans(cursor, production_date):
    plans = read_historical_plans(cursor, production_date)
    for plan in plans:
        plan["selection_id"] = hashlib.sha256(
            json.dumps(plan, default=str, sort_keys=True).encode()).hexdigest()
    return plans


def product_selection_context(cursor, selected):
    products = read_products(cursor)
    cursor.execute('''SELECT ProductFamily,ProductCode,MAX(RunningNo)+1
        FROM dbo.ProductionLot WHERE IsActive=1 AND ProductFamily IS NOT NULL
        AND SequenceMonth=? GROUP BY ProductFamily,ProductCode''',
        month_start(day(selected["StartTime"])))
    running = {(r[0], r[1]): int(r[2]) for r in cursor.fetchall()}
    previews = {}
    for product in products:
        family, code = product["ProductFamily"], product["ProductCode"]
        number = running.get((family, code), 1)
        stem = lot_prefix(family, code, selected["StartTime"])
        previews[family + "|" + code] = dict(
            ProductFamily=family, ProductCode=code, LotPrefix=stem,
            RunningNo=number, LotNo=f"{stem}{number:02d}")
    return dict(products=products, product_previews=previews)


def production_page(request, plan_id=None, product_code=None, confirm=False, mapping_edit=False,
                    create=False, running_no=None, production_date=None, production_id=None, edit=False, save=False, void=False, production_input=None, data_saved=False, product_family=None, product_choices=None, press_message=None, press_message_type=None, wet_reject_message=None, wet_reject_message_type=None):
    requested_date = production_date
    production_date = production_date or date.today()
    context = dict(families=FAMILIES, product_family=None, product_previews={}, production_data={}, calculated=calculate(None, None), data_saved=data_saved, production_date=production_date, lots=[], lots_for_date=[], production_data_by_lot={}, calculated_by_lot={}, current=None, edit=edit, edit_plans=[], plans=[], selected=None, products=[], material_prefix=None,
                   product_code=None, lot=None, error=None, lots_load_failed=False, running_no=None, created_lot=None,
                   press_production=[], day_start_time=None, eligible_presses=[], eligible_moulds=[], press_product_error=None,
                   press_message=press_message, press_message_type=press_message_type,
                   wet_reject_reasons=[], wet_reject_events=[], wet_reject_summary=[], wet_reject_total=0,
                   wet_reject_reason_groups=[], wet_reject_summary_groups=[],
                   wet_reject_now=datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                   wet_reject_message=wet_reject_message, wet_reject_message_type=wet_reject_message_type)
    status = 200
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            try:
                context["lots"] = read_lots(cursor)
            except Exception:
                context["lots_load_failed"] = True
                raise
            # Navigation may retain a lot only when it belongs to the selected date.
            # Keep all mutation paths and their validation/save behavior unchanged.
            if production_id is not None and not (confirm or create or save or void or production_input is not None):
                selected_lot = next((lot for lot in context['lots'] if lot['ProductionID'] == production_id), None)
                if selected_lot is not None:
                    if requested_date is None:
                        production_date = day(selected_lot['ProdDate'])
                        context['production_date'] = production_date
                    elif day(selected_lot['ProdDate']) != production_date:
                        production_id = None
                        context['edit'] = False
            context["lots_for_date"] = [lot for lot in context["lots"] if day(lot["ProdDate"]) == production_date]
            for index, lot in enumerate(context["lots_for_date"]):
                lot['CanMoveUp'] = index > 0
                lot['CanMoveDown'] = index < len(context["lots_for_date"]) - 1
            # The merged Production Lot row needs each Lot's own saved ProductionData,
            # not just the selected one; reuse the existing single-row reader per Lot.
            try:
                context["production_data_by_lot"] = {lot["ProductionID"]: read_production_data(cursor, lot["ProductionID"])
                                                     for lot in context["lots_for_date"]}
            except Exception:
                context["production_data_by_lot"] = {}
            context["calculated_by_lot"] = {pid: calculate(data.get("CounterQty"), data.get("CuringQty"))
                                            for pid, data in context["production_data_by_lot"].items()}
            if production_id is not None:
                current = next((lot for lot in context["lots"] if lot["ProductionID"] == production_id), None)
                if current is None:
                    raise ValueError("This Lot is no longer active.")
                lot_plans = read_plans(cursor, day(current["ProdDate"]))
                # Display the effective source row without rewriting the saved lot snapshot.
                effective = next((plan for plan in lot_plans
                    if plan["PlanName"] == current["PlanName"]), None)
                current = dict(current)
                if effective is not None:
                    current.update(MaterialCode=effective["MaterialCode"],
                        MaterialName=effective["MaterialName"], PlanQty=effective["PlanCount"],
                        VersionNo=effective.get("VersionNo"))
                context["current"] = current
                try:
                    context.update(build_press_production_context(cursor, current))
                except Exception:
                    context.update(press_production=[], eligible_presses=[], eligible_moulds=[],
                                   press_product_error='Unable to load Press Production choices or rows.')
                try:
                    context.update(build_wet_reject_context(cursor, production_id, production_date))
                except Exception:
                    pass
                if production_input is not None:
                    context["production_data"] = production_input
                    context["current"]["Shift"] = production_input.get("Shift", current["Shift"])
                    save_production_data(conn, production_id, production_input)
                    return RedirectResponse(f"/?production_id={production_id}&production_date={production_date}&data_saved=true", status_code=303)
                context["production_data"] = read_production_data(cursor, production_id)
                context["calculated"] = calculate(
                    context["production_data"].get("CounterQty"),
                    context["production_data"].get("CuringQty"))

                if edit or save:
                    context["edit_plans"] = mark_used(lot_plans, context["lots"], production_id)
                if save or void:
                    replacement = choose_plan(context["edit_plans"], plan_id) if save else None
                    update_lot(conn, production_id, replacement, void=void)
                    return RedirectResponse("/" if void else f"/?production_id={production_id}", status_code=303)
            context["plans"] = mark_used(read_plans(cursor, production_date), context["lots"])
            if plan_id:
                selected = choose_plan(context["plans"], plan_id)
                if selected is None:
                    raise ValueError("This plan changed or is no longer active. Select a current plan.")
                context["selected"] = selected
                material = selected["MaterialCode"] or ""
                if not material.strip():
                    raise ValueError("The selected plan has no MaterialCode.")
                prefix = material[:8]
                context["material_prefix"] = prefix
                if confirm:
                    try:
                        if product_choices is not None:
                            product_family, product_code = selected_product(product_choices)
                        product_family, product_code = confirm_mapping(conn, prefix, product_family, product_code,
                                                                        edit=mapping_edit)
                        mapping_edit = False
                    except ValueError:
                        context.update(product_selection_context(cursor, selected))
                        raise
                mapped = read_mapping(cursor, prefix)
                if mapped:
                    if mapping_edit:
                        context.update(product_selection_context(cursor, selected))
                        context["product_family"], context["product_code"] = mapped
                        context["mapping_edit"] = True
                    else:
                        context["product_family"], context["product_code"] = mapped
                        context["lot"] = lot_prefix(mapped[0], mapped[1], selected["StartTime"])
                        context["running_no"] = next_running_no(cursor, context["lot"],
                            mapped[0], mapped[1], selected["StartTime"])
                        if create:
                            new_id = insert_lot(conn, selected, mapped[1], context["lot"], running_no,
                                                product_family=mapped[0])
                            return RedirectResponse(f"/?production_id={new_id}&production_date={production_date}", status_code=303)
                else:
                    context.update(product_selection_context(cursor, selected))
                    if create:
                        raise ValueError("Confirm a ProductFamily / ProductCode mapping before creating a lot.")
            elif confirm or create:
                raise ValueError("Select a current plan first.")
    except ValueError as exc:
        context["error"] = str(exc)
        status = 400
    except Exception:
        context.update(error="Unable to load or save production data. Please try again.",
                       product_code=None, lot=None)
        status = 503
    return templates.TemplateResponse(request=request, name="production.html",
                                      context=context, status_code=status)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, plan_id: str | None = None, production_date: date | None = None,
         mapping_edit: bool = False,
        production_id: int | None = None, edit: bool = False, data_saved: bool = False,
        press_message: str | None = None, press_message_type: str | None = None,
        wet_reject_message: str | None = None, wet_reject_message_type: str | None = None):
    return production_page(request, plan_id, mapping_edit=mapping_edit, production_date=production_date, production_id=production_id,
                      edit=edit, data_saved=data_saved, press_message=press_message,
                      press_message_type=press_message_type, wet_reject_message=wet_reject_message,
                      wet_reject_message_type=wet_reject_message_type)


@app.post("/", response_class=HTMLResponse)
def confirm_product(request: Request, plan_id: str = Form(...), production_date: date = Form(...),
                    neufit: str = Form(""), oriental: str = Form(""),
                    special_ridge: str = Form(""), prestige_common: str = Form(""),
                    mapping_edit: bool = Form(False)):
    return production_page(request, plan_id, confirm=True, mapping_edit=mapping_edit, production_date=production_date,
                           product_choices=[neufit, oriental, special_ridge, prestige_common])


@app.post("/lots", response_class=HTMLResponse)
def create_lot(request: Request, plan_id: str = Form(...), running_no: int = Form(...), production_date: date = Form(...)):
    return production_page(request, plan_id, create=True, running_no=running_no, production_date=production_date)


@app.get("/health")
def health():
    return {"status": "ok", "service": "FittingMES"}


def reorder_lot_response(production_date, production_id, direction):
    try:
        with closing(get_connection()) as conn:
            return JSONResponse(jsonable_encoder(reorder_lot(conn, production_date, production_id, direction)))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Unable to reorder Production Lots. No changes were saved."}, status_code=503)


@app.post('/lots/{production_id}/move')
async def reorder_lot_route(production_id: int, request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid reorder request."}, status_code=400)
    if not isinstance(payload, dict) or set(payload) != {'production_date', 'direction'}:
        return JSONResponse({"error": "Invalid reorder request."}, status_code=400)
    return await run_in_threadpool(reorder_lot_response, payload['production_date'], production_id, payload['direction'])


def mark_used(plans, lots, exclude_id=None):
    plans = [dict(plan) for plan in plans]
    for plan in plans:
        plan["used_by"] = next((lot["LotNo"] for lot in lots
            if day(lot["ProdDate"]) == day(plan["StartTime"]) and lot["PlanName"] == plan["PlanName"]
            and lot["ProductionID"] != exclude_id), None)
    return plans


def choose_plan(plans, plan_id):
    selected = next((p for p in plans if p["selection_id"] == plan_id), None)
    if selected is None:
        raise ValueError("This plan changed or is no longer available. Refresh plans.")
    if selected.get("used_by"):
        raise ValueError("This plan is already assigned to another active Lot.")
    return selected


@app.post("/lots/{production_id}/plan", response_class=HTMLResponse)
def save_plan(request: Request, production_id: int, plan_id: str = Form(...)):
    return production_page(request, plan_id, production_id=production_id, edit=True, save=True)


@app.post("/lots/{production_id}/void", response_class=HTMLResponse)
def void_lot(request: Request, production_id: int):
    return production_page(request, production_id=production_id, void=True)


@app.post("/lots/{production_id}/production", response_class=HTMLResponse)
def save_production(request: Request, production_id: int,
                    shift: str = Form(""), start_time: str = Form(""),
                    end_time: str = Form(""), counter: str = Form(""),
                    curing: str = Form(""), remark: str = Form(""),
                    production_date: date | None = Form(None)):
    raw = dict(Shift=shift, ProductionStartTime=start_time,
               ProductionEndTime=end_time, CounterQty=counter,
               CuringQty=curing, Remark=remark)
    return production_page(request, production_id=production_id,
                           production_date=production_date, production_input=raw)


def save_press_production_change(production_id, data, press_production_id=None):
    with closing(get_connection()) as conn:
        return save_press_production_row(conn, production_id, data, press_production_id)


def release_press_production_change(production_id, press_production_id):
    with closing(get_connection()) as conn:
        return release_press_production(conn, production_id, press_production_id)


def undo_release_press_production_change(production_id, press_production_id):
    with closing(get_connection()) as conn:
        return undo_release_press_production(conn, production_id, press_production_id)


def press_production_redirect(production_id, message, message_type='success'):
    params = {'production_id': production_id, 'press_message': message,
              'press_message_type': message_type}
    return RedirectResponse('/?' + urlencode(params), status_code=303)


async def save_press_production_route_action(request, production_id, press_production_id=None):
    form = await request.form()
    data = dict(MachineCode=form.get('machine_code'), MouldID=form.get('mould_id'),
                ProductionDate=form.get('production_date'),
                DispatchQty=form.get('dispatch_qty'), CounterQty=form.get('counter_qty'),
                CuringQty=form.get('curing_qty'),
                ProductionStartTime=form.get('production_start_time'),
                ProductionEndTime=form.get('production_end_time'), Remark=form.get('remark'),
                SetupMinutes=form.get('setup_minutes'), ChgOverMinutes=form.get('chgover_minutes'),
                IdleMinutes=form.get('idle_minutes'), CleaningMinutes=form.get('cleaning_minutes'),
                BreakdownMinutes=form.get('breakdown_minutes'))
    try:
        await run_in_threadpool(save_press_production_change, production_id, data, press_production_id)
        return press_production_redirect(production_id, 'Press Production saved.')
    except ValueError as exc:
        return press_production_redirect(production_id, str(exc), 'error')
    except Exception:
        return press_production_redirect(production_id, 'Unable to save Press Production. Please retry.', 'error')


@app.post('/lots/{production_id}/press-production')
async def add_press_production_route(request: Request, production_id: int):
    return await save_press_production_route_action(request, production_id)


@app.post('/lots/{production_id}/press-production/{press_production_id}/release')
async def release_press_production_route(request: Request, production_id: int,
                                         press_production_id: int):
    try:
        result = await run_in_threadpool(
            release_press_production_change, production_id, press_production_id)
        message = ('Press Production already released.' if result == 'ALREADY_RELEASED'
                   else 'Mould released.')
        return press_production_redirect(production_id, message)
    except ValueError as exc:
        return press_production_redirect(production_id, str(exc), 'error')
    except Exception:
        return press_production_redirect(production_id, 'Unable to release Mould. Please retry.', 'error')


@app.post('/lots/{production_id}/press-production/{press_production_id}/undo-release')
async def undo_release_press_production_route(request: Request, production_id: int,
                                              press_production_id: int):
    try:
        result = await run_in_threadpool(
            undo_release_press_production_change, production_id, press_production_id)
        messages = {'RESTORED': 'Mould assignment restored.',
                    'ALREADY_ACTIVE': 'Press Production is already active.',
                    'MOULD_ALREADY_REASSIGNED': 'MOULD_ALREADY_REASSIGNED: this Mould is already assigned to another Press.'}
        return press_production_redirect(
            production_id, messages.get(result, 'Mould assignment restored.'))
    except ValueError as exc:
        return press_production_redirect(production_id, str(exc), 'error')
    except Exception:
        return press_production_redirect(production_id, 'Unable to undo Mould release. Please retry.', 'error')


@app.post('/lots/{production_id}/press-production/{press_production_id}')
async def update_press_production_route(request: Request, production_id: int,
                                        press_production_id: int):
    return await save_press_production_route_action(request, production_id, press_production_id)


def save_wet_reject_change(production_id, data, wet_reject_id=None):
    with closing(get_connection()) as conn:
        return save_wet_reject(conn, production_id, data, wet_reject_id)


def wet_reject_redirect(production_id, message, message_type='success'):
    params = {'production_id': production_id, 'wet_reject_message': message,
              'wet_reject_message_type': message_type}
    return RedirectResponse('/?' + urlencode(params), status_code=303)


async def save_wet_reject_route_action(request, production_id, wet_reject_id=None):
    form = await request.form()
    data = dict(ReasonCode=form.get('reason_code'), Qty=form.get('qty'), Remark=form.get('remark'))
    try:
        await run_in_threadpool(save_wet_reject_change, production_id, data, wet_reject_id)
        return wet_reject_redirect(production_id, 'Wet Reject saved.')
    except ValueError as exc:
        return wet_reject_redirect(production_id, str(exc), 'error')
    except Exception:
        return wet_reject_redirect(production_id, 'Unable to save Wet Reject. Please retry.', 'error')


@app.post('/lots/{production_id}/wet-reject')
async def add_wet_reject_route(request: Request, production_id: int):
    return await save_wet_reject_route_action(request, production_id)


def save_wet_reject_batch_change(production_id, data):
    with closing(get_connection()) as conn:
        return save_wet_reject_batch(conn, production_id, data)


@app.post('/lots/{production_id}/wet-reject/batch')
async def add_wet_reject_batch_route(request: Request, production_id: int):
    form = await request.form()
    quantities = {key[len('qty_'):]: value for key, value in form.multi_items() if key.startswith('qty_')}
    data = dict(Remark=form.get('remark'), Quantities=quantities)
    try:
        await run_in_threadpool(save_wet_reject_batch_change, production_id, data)
        return wet_reject_redirect(production_id, 'Wet Reject saved.')
    except ValueError as exc:
        return wet_reject_redirect(production_id, str(exc), 'error')
    except Exception:
        return wet_reject_redirect(production_id, 'Unable to save Wet Reject. Please retry.', 'error')


@app.post('/lots/{production_id}/wet-reject/{wet_reject_id}')
async def update_wet_reject_route(request: Request, production_id: int, wet_reject_id: int):
    return await save_wet_reject_route_action(request, production_id, wet_reject_id)


@app.get("/depallet", response_class=HTMLResponse)
def depallet_page(request: Request, production_date: date | None = None,
                  production_id: int | None = None, depallet_id: int | None = None):
    production_date = production_date or date.today()
    context = dict(page_title="DEPALLET", active_tab="depallet", production_date=production_date,
                   lots=[], products=[], families=FAMILIES, entries={}, runs=[], current=None,
                   current_run_id=depallet_id, error=None, r99_name="", daily_totals={},
                   day_start_time=None)
    status = 200
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            context["lots"] = read_curing_lots(cursor)
            context["products"] = read_products(cursor)
            (context["entries"], context["runs"], context["reject_reasons"],
             context["daily_totals"], context["day_start_time"]) = read_daily_work(
                cursor, production_date, context["lots"])
            if context["lots"]:
                selected_run = next((run for run in context['runs']
                                     if run['DepalletID'] == depallet_id), None)
                if selected_run is None and production_id is not None:
                    selected_run = next((run for run in context['runs']
                                         if run['ProductionID'] == production_id), None)
                if selected_run is None and production_id is None and depallet_id is None and context['runs']:
                    selected_run = context['runs'][0]
                context['current_run_id'] = selected_run['DepalletID'] if selected_run else None
                context["current"] = next((lot for lot in context["lots"]
                    if lot['ProductionID'] == (selected_run['ProductionID'] if selected_run else production_id)), None)
                if context['current'] is None and context['lots']:
                    context['current'] = next((lot for lot in context['lots']
                        if lot['ProductionID'] == context['runs'][0]['ProductionID']), context['lots'][0]) if context['runs'] else context['lots'][0]
                context['r99_name'] = next((reason['ReasonNameTH'] for reason in
                    read_depallet_reasons(cursor, include_r99=True) if reason['ReasonCode'] == 'R99'), '')
    except ValueError as exc:
        context["error"] = str(exc)
        status = 400
    except Exception:
        context["error"] = "Unable to load Depallet data. Reload the page to retry."
        status = 503
    context['entries_json'] = jsonable_encoder(context['entries'])
    context['runs_json'] = jsonable_encoder(context['runs'])
    context['lots_json'] = jsonable_encoder(context['lots'])
    context['products_json'] = jsonable_encoder(context['products'])
    context['reasons_json'] = jsonable_encoder(context.get('reject_reasons', []))
    context['daily_totals_json'] = jsonable_encoder(context['daily_totals'])
    context['day_start_time_text'] = context['day_start_time'].strftime('%H:%M') \
        if isinstance(context['day_start_time'], time) else ''
    return templates.TemplateResponse(request=request, name="depallet.html", context=context, status_code=status)


@app.get("/lots/{production_id}/depallet")
def load_depallet(production_id: int, depallet_date: date, depallet_id: int | None = None):
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM dbo.ProductionLot WHERE ProductionID=? AND IsActive=1", production_id)
            found = rows(cursor)
            if not found:
                raise ValueError("This Production Lot is no longer active.")
            result = read_depallet_context(cursor, found[0], depallet_date, depallet_id)
            return JSONResponse(jsonable_encoder(result), headers={"Cache-Control": "no-store"})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Unable to load Depallet data. Please retry."}, status_code=503)


def save_depallet_response(production_id, raw):
    try:
        with closing(get_connection()) as conn:
            saved = save_depallet(conn, production_id, raw)
            return JSONResponse(jsonable_encoder({"depallet": saved, "message": "Depallet data saved."}))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Unable to save Depallet data. Nothing was saved; please retry."}, status_code=503)


def save_depallet_batch_response(depallet_date, items):
    try:
        with closing(get_connection()) as conn:
            saved = save_depallet_batch(conn, depallet_date, items)
            return JSONResponse(jsonable_encoder({"rows": saved, "message": "Depallet data saved."}))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Unable to save Depallet data. Nothing was saved; please retry."}, status_code=503)


def reorder_depallet_response(depallet_date, depallet_id, direction):
    try:
        with closing(get_connection()) as conn:
            result = reorder_depallet_run(conn, depallet_date, depallet_id, direction)
            return JSONResponse(jsonable_encoder(result))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "Unable to reorder Depallet runs. No changes were saved."}, status_code=503)


@app.post("/depallet/{depallet_id}/move")
async def reorder_depallet_route(depallet_id: int, request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid reorder request."}, status_code=400)
    if not isinstance(payload, dict) or set(payload) != {"production_date", "direction"}:
        return JSONResponse({"error": "Invalid reorder request."}, status_code=400)
    return await run_in_threadpool(reorder_depallet_response,
        payload["production_date"], depallet_id, payload["direction"])


@app.post("/depallet/save")
async def save_depallet_batch_route(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid Depallet data."}, status_code=400)
    if not isinstance(payload, dict) or set(payload) != {"depallet_date", "rows"}:
        return JSONResponse({"error": "Invalid Depallet data."}, status_code=400)
    return await run_in_threadpool(save_depallet_batch_response,
                                   payload["depallet_date"], payload["rows"])


@app.post("/lots/{production_id}/depallet")
async def save_depallet_route(request: Request, production_id: int):
    form = await request.form()
    # Reject duplicate field submissions instead of silently taking one value.
    if any(len(form.getlist(key)) != 1 for key in form):
        return JSONResponse({"error": "Duplicate Depallet fields are not allowed."}, status_code=400)
    raw = dict(DepalletDate=form.get("depallet_date"), Shift=form.get("shift"),
               DepalletID=form.get("depallet_id"), LotNo=form.get("lot_no"),
               Start=form.get("start"), End=form.get("end"), DepalletQty=form.get("depallet_qty"),
               GoodQty=form.get("good_qty"), Remark=form.get("remark"),
               rejects={key[len("reject_"):]: value for key, value in form.items() if key.startswith("reject_")})
    return await run_in_threadpool(save_depallet_response, production_id, raw)


@app.get("/prod-api", response_class=HTMLResponse)
def prod_api_page(request: Request, production_date: date | None = None,
                  preview_all: bool = False, preview_one: bool = False,
                  production_id: int | None = None, send_message: str | None = None,
                  send_error: str | None = None, send_groups: int = 0, send_lots: int = 0,
                  send_success: int = 0, send_failed: int = 0, send_unknown: int = 0,
                  skipped_not_ready: int = 0, skipped_sent: int = 0, skipped_unknown: int = 0):
    production_date = production_date or date.today()
    context = dict(page_title="PROD API", active_tab="prod-api", production_date=production_date,
                   records=[], previews=[], selected_id=production_id, error=None, diagnostics=[], group_count=0,
                   preview_all=preview_all, preview_count=0, lot_readiness=lot_readiness,
                   pis_config=PISConfig.from_environment().diagnostics(), send_message=send_message,
                   send_error=send_error, send_groups=send_groups, send_lots=send_lots,
                   send_success=send_success, send_failed=send_failed, send_unknown=send_unknown,
                   skipped_not_ready=skipped_not_ready, skipped_sent=skipped_sent,
                   skipped_unknown=skipped_unknown)
    status = 200
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            context["records"] = read_prod_records(cursor, production_date)
            states = latest_states(cursor, [row['ProductionID'] for row in context['records']])
            for record in context['records']:
                state = states.get(record['ProductionID'])
                record['DeliveryStatus'] = ({'SUCCESS': 'SENT', 'FAILED': 'FAILED', 'UNKNOWN': 'UNKNOWN'}
                                            .get(state['Outcome'], 'NOT SENT') if state else 'NOT SENT')
        if preview_all or preview_one:
            if not context["records"]:
                context["error"] = "No active Production Lots for this date. Nothing to preview."
            else:
                selected_records = [row for row in context['records'] if row['ProductionID'] == production_id]
                if preview_one and selected_records and not lot_readiness(selected_records[0])['ready']:
                    missing = ', '.join(lot_readiness(selected_records[0])['missing'])
                    context['error'] = f"Production Lot is NOT READY. Missing: {missing}."
                    status = 400
                    selected_records = []
                preview_records = ([row for row in context['records'] if lot_readiness(row)['ready']]
                                   if preview_all else selected_records)
                if not preview_records:
                    if not context['error']:
                        context['error'] = 'Select a Production Lot from this date that is READY to preview.'
                        status = 400
                for record in preview_records:
                    mapping = field_mapping(record)
                    context['diagnostics'].append(dict(record=record, mapping=mapping,
                        missing=lot_readiness(record)['missing']))
                groups = build_pis_date_preview(preview_records, production_date) if preview_records else []
                context['preview_count'] = len(preview_records)
                context['group_count'] = len(groups)
                context['missing'] = any(item['missing'] for item in context['diagnostics'])
                context['previews'] = [dict(payload=group, readiness=preview_readiness(group, preview_records), json=json.dumps(
                    jsonable_encoder(group), ensure_ascii=False, indent=2)) for group in groups]
    except Exception:
        context.update(records=[], previews=[], diagnostics=[],
                       error="Unable to load Production records. Please retry.")
        status = 503
    return templates.TemplateResponse(request=request, name="prod_api.html", context=context,
                                      status_code=status, headers={"Cache-Control": "no-store"})


def _prod_redirect(production_date, **values):
    query = {'production_date': str(production_date)}
    query.update({key: str(value) for key, value in values.items() if value not in (None, '')})
    return RedirectResponse('/prod-api?' + urlencode(query), status_code=303)


def _send_config_or_error():
    config = PISConfig.from_environment()
    if not config.production_send_enabled:
        return None, 'Production sending is disabled by PIS_PROD_SEND_ENABLED.'
    if not config.endpoint_configured:
        return None, 'Production sending is unavailable because the PIS endpoint is not configured.'
    if not config.authentication_configured:
        return None, 'Production sending is unavailable because PIS authentication is not configured.'
    return config, None


def _prod_records_and_states(conn, production_date):
    cursor = conn.cursor()
    records = read_prod_records(cursor, production_date)
    states = latest_states(cursor, [row['ProductionID'] for row in records])
    for record in records:
        state = states.get(record['ProductionID'])
        record['DeliveryStatus'] = ({SUCCESS: 'SENT', FAILED: 'FAILED', UNKNOWN: 'UNKNOWN'}
                                    .get(state['Outcome'], 'NOT SENT') if state else 'NOT SENT')
    return records, states


def _send_one(production_date, production_id, unknown_retry=False):
    batch_run_id = uuid4()
    config, error = _send_config_or_error()
    if error:
        return _prod_redirect(production_date, send_error=error)
    with closing(get_connection()) as conn:
        records, states = _prod_records_and_states(conn, production_date)
        record = next((row for row in records if row['ProductionID'] == production_id), None)
        if record is None:
            return _prod_redirect(production_date, send_error='Select an active Production Lot from this date.')
        readiness = lot_readiness(record)
        if not readiness['ready']:
            insert_audit_rows(conn, [audit_row(
                batch_run_id, 'PROD', 'SINGLE', record['LotNo'], 'SKIP',
                'NOT_READY: ' + ', '.join(readiness['missing']),
                send_date=record['ProdDate'], PlantCode=record.get('Plant'),
                MachineCode=record.get('Machine'), ShiftID=record.get('Shift'))])
            conn.commit()
            return _prod_redirect(production_date, send_error='Production Lot is NOT READY. Missing: ' + ', '.join(readiness['missing']) + '.')
        state = states.get(production_id)
        if state and state['Outcome'] == SUCCESS:
            return _prod_redirect(production_date, send_error='This Production Lot is already SENT.')
        if state and state['Outcome'] == UNKNOWN and not unknown_retry:
            return _prod_redirect(production_date, send_error='This Production Lot has UNKNOWN delivery status. Use RETRY UNKNOWN explicitly.')
        results = send_ready_groups(conn, [record], PISClient(config), include_unknown=unknown_retry,
                        audit_batch_id=batch_run_id, audit_mode='SINGLE')
        if not results:
            return _prod_redirect(production_date, send_error='This Production Lot is not eligible for sending.')
        result = results[0]
        return _prod_redirect(production_date, send_message='Production send completed.', send_groups=1,
                              send_lots=1, send_success=int(result['outcome'] == SUCCESS),
                              send_failed=int(result['outcome'] == FAILED), send_unknown=int(result['outcome'] == UNKNOWN))


@app.post('/prod-api/send')
def send_prod(request: Request, production_date: date = Form(...), production_id: int = Form(...)):
    return _send_one(production_date, production_id)


@app.post('/prod-api/retry-unknown')
def retry_unknown_prod(request: Request, production_date: date = Form(...), production_id: int = Form(...)):
    return _send_one(production_date, production_id, unknown_retry=True)


@app.post('/prod-api/send-all')
def send_all_prod(request: Request, production_date: date = Form(...)):
    batch_run_id = uuid4()
    config, error = _send_config_or_error()
    if error:
        return _prod_redirect(production_date, send_error=error)
    with closing(get_connection()) as conn:
        records, states = _prod_records_and_states(conn, production_date)
        skipped_not_ready = sum(not lot_readiness(row)['ready'] for row in records)
        skipped_sent = sum(state and state['Outcome'] == SUCCESS for state in states.values())
        skipped_unknown = sum(state and state['Outcome'] == UNKNOWN for state in states.values())
        not_ready_rows = []
        for record in records:
            readiness = lot_readiness(record)
            if not readiness['ready']:
                not_ready_rows.append(audit_row(
                    batch_run_id, 'PROD', 'BATCH', record['LotNo'], 'SKIP',
                    'NOT_READY: ' + ', '.join(readiness['missing']),
                    send_date=record['ProdDate'], PlantCode=record.get('Plant'),
                    MachineCode=record.get('Machine'), ShiftID=record.get('Shift')))
        insert_audit_rows(conn, not_ready_rows)
        results = send_ready_groups(conn, records, PISClient(config),
                                    audit_batch_id=batch_run_id, audit_mode='BATCH')
        if not_ready_rows:
            conn.commit()
    return _prod_redirect(production_date, send_message='Production SEND ALL completed.',
                          send_groups=len(results), send_lots=sum(len(result['production_ids']) for result in results),
                          send_success=sum(result['outcome'] == SUCCESS for result in results for _ in result['production_ids']),
                          send_failed=sum(result['outcome'] == FAILED for result in results for _ in result['production_ids']),
                          send_unknown=sum(result['outcome'] == UNKNOWN for result in results for _ in result['production_ids']),
                          skipped_not_ready=skipped_not_ready, skipped_sent=skipped_sent,
                          skipped_unknown=skipped_unknown)


@app.get("/reject-api", response_class=HTMLResponse)
def reject_api_page(request: Request, production_date: date | None = None,
                    production_id: int | None = None, preview_one: bool = False,
                    preview_all: bool = False, lookup_one: bool = False,
                    lookup_all: bool = False):
    production_date = production_date or date.today()
    context = dict(page_title='REJECT API', active_tab='reject-api', production_date=production_date,
                   records=[], selected_id=production_id, previews=[], lookup_results=[],
                   error=None, lookup_errors=[], preview_one=preview_one, preview_all=preview_all,
                   lookup_one=lookup_one, lookup_all=lookup_all)
    status = 200
    try:
        with closing(get_connection()) as conn:
            records = read_reject_records(conn.cursor(), production_date)
            for record in records:
                reject_readiness(record)
            try:
                states = latest_reject_states(conn.cursor(), [row['ProductionID'] for row in records])
            except Exception:
                # RejectPISLog is optional history; its migration may not exist on SB23 yet.
                states = {}
            for record in records:
                state = states.get(record['ProductionID'])
                record['RejectPISStatus'] = state['Outcome'] if state else 'NOT SENT'
            context['records'] = records
            if preview_one or preview_all:
                if preview_one:
                    selected = next((row for row in records if row['ProductionID'] == production_id), None)
                    if selected is None:
                        raise ValueError('Select one Production Lot for PREVIEW REJECT.')
                    candidates = [selected]
                else:
                    candidates = records
                for record in candidates:
                    if record['RejectReadiness']['ready']:
                        context['previews'].append(dict(record=record, payload=build_reject_preview(record)))
                    elif preview_one:
                        raise ValueError('NOT READY: ' + '; '.join(record['RejectReadiness']['missing']))
            if lookup_one or lookup_all:
                if lookup_one:
                    selected = next((row for row in records if row['ProductionID'] == production_id), None)
                    if selected is None:
                        raise ValueError('Select one Production Lot for OUTPUTDETAILS LOOKUP.')
                    candidates = [selected]
                else:
                    candidates = records
                config = PISConfig.from_environment()
                if not config.endpoint_configured or not config.authentication_configured:
                    context['lookup_errors'].append('PIS lookup unavailable: endpoint or authentication is not configured.')
                else:
                    client = PISClient(config)
                    for record in candidates:
                        if not record['RejectReadiness']['ready']:
                            context['lookup_errors'].append(
                                f"{record['LotNo']}: NOT READY: " + '; '.join(record['RejectReadiness']['missing']))
                            continue
                        try:
                            query = build_output_details_query(record)
                            response = client.get_output_details(query)
                            output_details = parse_output_details_response(response)
                            if not output_details:
                                context['lookup_errors'].append(f"{record['LotNo']}: NO_OUTPUT_DETAILS")
                                continue
                            summary = summarize_output_details(output_details)
                            payload = build_change_status_preview(record, summary)
                            context['lookup_results'].append(dict(record=record, query=query,
                                                                  output_details=output_details,
                                                                  summary=summary, payload=payload))
                        except (PISClientError, ValueError) as exc:
                            context['lookup_errors'].append(f"{record['LotNo']}: {exc}")
    except ValueError as exc:
        context['error'] = str(exc)
        status = 400
    except Exception:
        context['error'] = 'Unable to load Reject API records. Please retry.'
        status = 503
    return templates.TemplateResponse(request=request, name='reject_api.html', context=context,
                                      status_code=status, headers={'Cache-Control': 'no-store'})


@app.post('/reject-api/{production_id}/send', response_class=HTMLResponse)
def reject_api_send(request: Request, production_id: int, production_date: date | None = None):
    production_date = production_date or date.today()
    try:
        from app.reject_api import parse_output_details_response, summarize_output_details
        from app.pis_config import PISConfig
        with closing(get_connection()) as conn:
            records = read_reject_records(conn.cursor(), production_date)
            record = next((row for row in records if row['ProductionID'] == production_id), None)
            if record is None:
                raise ValueError('Production lot was not found for the selected date.')
            config = PISConfig.from_environment()
            client = PISClient(config)
            def output_loader(item):
                output_details = parse_output_details_response(
                    client.get_output_details(build_output_details_query(item)))
                return summarize_output_details(output_details) if output_details else {'noOutputDetails': True}
            def cumulative_loader(item):
                return dict(CuringCnt=item.get('CuringQty'), ToPackCnt=item.get('CounterQty'),
                            ShiftID=item.get('Shift'), DateDepallet=item.get('ProdDate'),
                            dt=max((row.get('RejectDateTime') for row in item.get('RejectRows', [])
                                    if row.get('RejectDateTime')), default=None),
                            **{f'Rej_{code}': sum(int(row.get('Qty') or 0) for row in item.get('RejectRows', [])
                                                  if row.get('ReasonCode') == code)
                               for code in ('R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R08', 'R12', 'R13')})
            result = send_reject_single(conn, record, output_loader, cumulative_loader, config=config,
                                        client=client)
        message = f"{record['LotNo']}: {result['status']} - {result['reason']}"
        return RedirectResponse('/reject-api?production_date=' + str(production_date) +
                                '&send_message=' + quote(message), status_code=303)
    except ValueError as exc:
        return RedirectResponse('/reject-api?production_date=' + str(production_date) +
                                '&send_message=' + quote(str(exc)), status_code=303)


@app.get("/press-mc", response_class=HTMLResponse)
def press_mc_page(request: Request, production_date: date | None = None,
                  press_code: str | None = None, message: str | None = None,
                  message_type: str | None = None):
    production_date = production_date or date.today()
    context = dict(page_title="PressMc", active_tab="press-mc", production_date=production_date,
                   presses=[], lines=[], selected=None, capability_groups=[], history=[], error=None,
                   message=message, message_type=message_type)
    status = 200
    try:
        with closing(get_connection()) as conn:
            context.update(press_mc_context(conn.cursor(), press_code))
    except ValueError as exc:
        context['error'] = str(exc)
        status = 400
    except Exception:
        context['error'] = 'Unable to load Press configuration. Please retry.'
        status = 503
    return templates.TemplateResponse(request=request, name='press_mc.html', context=context,
                                      status_code=status, headers={'Cache-Control':'no-store'})


def press_mc_redirect(press_code=None, message=None, message_type='success', production_date=None):
    params = {}
    if production_date:
        params['production_date'] = str(production_date)
    if press_code:
        params['press_code'] = press_code
    if message:
        params['message'] = message
        params['message_type'] = message_type
    return RedirectResponse('/press-mc' + ('?' + urlencode(params) if params else ''), status_code=303)


def run_press_mc_change(operation, *args):
    try:
        with closing(get_connection()) as conn:
            result = operation(conn, *args)
        return result
    except ValueError:
        raise


def save_press_mc_capabilities(press_code, changes, remark):
    with closing(get_connection()) as conn:
        return save_capabilities(conn, press_code, changes, remark)


@app.post('/press-mc/add')
async def press_mc_add_route(request: Request):
    form = await request.form()
    try:
        press_code = await run_in_threadpool(run_press_mc_change, add_press,
            form.get('press_code'), form.get('press_name'), form.get('line_code'), form.get('remark'))
        return press_mc_redirect(press_code, 'Press machine added.', production_date=form.get('production_date'))
    except ValueError as exc:
        return press_mc_redirect(form.get('press_code'), str(exc), 'error', form.get('production_date'))
    except Exception:
        return press_mc_redirect(form.get('press_code'), 'Unable to add Press machine.', 'error', form.get('production_date'))


@app.post('/press-mc/{press_code}/name')
async def press_mc_name_route(press_code: str, request: Request):
    form = await request.form()
    try:
        await run_in_threadpool(run_press_mc_change, update_press_name, press_code, form.get('press_name'))
        return press_mc_redirect(press_code, 'Press name saved.', production_date=form.get('production_date'))
    except ValueError as exc:
        return press_mc_redirect(press_code, str(exc), 'error', form.get('production_date'))
    except Exception:
        return press_mc_redirect(press_code, 'Unable to update Press name.', 'error', form.get('production_date'))


@app.post('/press-mc/{press_code}/line')
async def press_mc_line_route(press_code: str, request: Request):
    form = await request.form()
    try:
        await run_in_threadpool(run_press_mc_change, assign_line, press_code,
                                form.get('line_code'), form.get('remark'))
        return press_mc_redirect(press_code, 'Press Line assignment saved.', production_date=form.get('production_date'))
    except ValueError as exc:
        return press_mc_redirect(press_code, str(exc), 'error', form.get('production_date'))
    except Exception:
        return press_mc_redirect(press_code, 'Unable to update Press Line.', 'error', form.get('production_date'))


@app.post('/press-mc/{press_code}/remove-line')
async def press_mc_remove_line_route(press_code: str, request: Request):
    form = await request.form()
    try:
        await run_in_threadpool(run_press_mc_change, remove_from_line, press_code, form.get('remark'))
        return press_mc_redirect(press_code, 'Press is now unassigned from a Line.', production_date=form.get('production_date'))
    except ValueError as exc:
        return press_mc_redirect(press_code, str(exc), 'error', form.get('production_date'))
    except Exception:
        return press_mc_redirect(press_code, 'Unable to remove Press from Line.', 'error', form.get('production_date'))


@app.post('/press-mc/{press_code}/active')
async def press_mc_active_route(press_code: str, request: Request):
    form = await request.form()
    try:
        active = str(form.get('is_active') or '') == '1'
        await run_in_threadpool(run_press_mc_change, set_active, press_code, active, form.get('remark'))
        return press_mc_redirect(press_code, 'Press status updated.', production_date=form.get('production_date'))
    except ValueError as exc:
        return press_mc_redirect(press_code, str(exc), 'error', form.get('production_date'))
    except Exception:
        return press_mc_redirect(press_code, 'Unable to update Press status.', 'error', form.get('production_date'))


@app.post('/press-mc/{press_code}/capabilities')
async def press_mc_capability_route(press_code: str, request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({'error':'Invalid capability request.'}, status_code=400)
    if not isinstance(payload, dict) or set(payload) - {'changes','remark'} or 'changes' not in payload:
        return JSONResponse({'error':'Invalid capability request.'}, status_code=400)
    try:
        await run_in_threadpool(save_press_mc_capabilities, press_code,
                                payload['changes'], payload.get('remark',''))
        return JSONResponse({'message':'Press capability changes saved.'})
    except ValueError as exc:
        return JSONResponse({'error':str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({'error':'Unable to save Press capability changes.'}, status_code=503)


@app.get('/mould', response_class=HTMLResponse)
def mould_page(request: Request, production_date: date | None = None, q: str = '',
               product: str = '', status: str = '', mould_id: int | None = None,
               message: str | None = None, message_type: str | None = None):
    production_date = production_date or date.today()
    context = dict(page_title='Mould', active_tab='mould', production_date=production_date,
                   search=q, product_filter=product, status_filter=status, moulds=[], products=[],
                   selected=None, status_history=[], recondition_history=[], usage_history=[],
                   message=message, message_type=message_type, error=None)
    response_status = 200
    try:
        with closing(get_connection()) as conn:
            context.update(mould_context(conn.cursor(), q, product, status, mould_id))
    except ValueError as exc:
        context['error'] = str(exc)
        response_status = 400
    except Exception:
        context['error'] = 'Unable to load Mould information. Please retry.'
        response_status = 503
    return templates.TemplateResponse(request=request, name='mould.html', context=context,
                                      status_code=response_status,
                                      headers={'Cache-Control': 'no-store'})


def mould_redirect(mould_id=None, message=None, message_type='success'):
    params = {}
    if mould_id:
        params['mould_id'] = mould_id
    if message:
        params['message'] = message
        params['message_type'] = message_type
    return RedirectResponse('/mould' + ('?' + urlencode(params) if params else ''), status_code=303)


def run_mould_change(operation, *args):
    with closing(get_connection()) as conn:
        return operation(conn, *args)


@app.post('/mould/register')
async def mould_register_route(request: Request):
    form = await request.form()
    try:
        mould = await run_in_threadpool(run_mould_change, register_mould, form.get('mould_name'),
                                        form.get('product_family'), form.get('product_code'),
                                        form.get('remark'))
        return mould_redirect(mould['MouldID'], f"Registered {mould['MouldNo']}.")
    except ValueError as exc:
        return mould_redirect(message=str(exc), message_type='error')
    except Exception:
        return mould_redirect(message='Unable to register Mould. Please retry.', message_type='error')


async def mould_mutation_route(request: Request, mould_id: int, operation, success_message):
    form = await request.form()
    try:
        mould = await run_in_threadpool(run_mould_change, operation, mould_id, form.get('remark', ''))
        return mould_redirect(mould['MouldID'], success_message)
    except ValueError as exc:
        return mould_redirect(mould_id, str(exc), 'error')
    except Exception:
        return mould_redirect(mould_id, 'Unable to update Mould. Please retry.', 'error')


@app.post('/mould/{mould_id}/edit')
async def mould_edit_route(request: Request, mould_id: int):
    form = await request.form()
    try:
        mould = await run_in_threadpool(run_mould_change, update_mould_info, mould_id,
                                        form.get('mould_name'), form.get('remark'))
        return mould_redirect(mould['MouldID'], 'Mould information saved.')
    except ValueError as exc:
        return mould_redirect(mould_id, str(exc), 'error')
    except Exception:
        return mould_redirect(mould_id, 'Unable to update Mould information. Please retry.', 'error')


@app.post('/mould/{mould_id}/recondition/start')
async def mould_send_route(request: Request, mould_id: int):
    return await mould_mutation_route(request, mould_id, send_to_recondition,
                                      'Mould sent to recondition.')


@app.post('/mould/{mould_id}/return')
async def mould_return_route(request: Request, mould_id: int):
    return await mould_mutation_route(request, mould_id, return_from_recondition,
                                      'Mould returned to ACTIVE.')


@app.post('/mould/{mould_id}/status')
async def mould_status_route(request: Request, mould_id: int):
    form = await request.form()
    try:
        mould = await run_in_threadpool(run_mould_change, set_mould_status, mould_id,
                                        form.get('new_status'), form.get('remark', ''))
        return mould_redirect(mould['MouldID'], f"Mould status changed to {mould['Status']}.")
    except ValueError as exc:
        return mould_redirect(mould_id, str(exc), 'error')
    except Exception:
        return mould_redirect(mould_id, 'Unable to change Mould status. Please retry.', 'error')


@app.get('/usage', response_class=HTMLResponse)
def usage_page(request: Request, production_date: date | None = None, saved: bool = False):
    production_date = production_date or date.today()
    context = dict(page_title='USAGE', active_tab='usage', production_date=production_date,
                   lots=[], shifts=[], daily=[], error=None, saved=saved)
    status = 200
    try:
        with closing(get_connection()) as conn:
            context.update(read_usage_context(conn.cursor(), production_date))
    except ValueError as exc:
        context['error'] = str(exc)
        status = 400
    except Exception:
        context['error'] = 'Unable to load material usage. Please retry.'
        status = 503
    return templates.TemplateResponse(request=request, name='usage.html', context=context,
                                      status_code=status, headers={'Cache-Control':'no-store'})


@app.get('/print-prod', response_class=HTMLResponse)
def print_prod_page(request: Request, production_date: date | None = None):
    production_date = production_date or date.today()
    context = dict(page_title='PRINT PROD', active_tab='print-prod', production_date=production_date,
                   records=[], shifts=[], daily_materials=[], error=None)
    status = 200
    try:
        with closing(get_connection()) as conn:
            context.update(read_print_prod_context(conn.cursor(), production_date))
    except ValueError as exc:
        context['error'] = str(exc)
        status = 400
    except Exception:
        context['error'] = 'Unable to load the production report. Please retry.'
        status = 503
    return templates.TemplateResponse(request=request, name='print_prod.html', context=context,
                                      status_code=status, headers={'Cache-Control':'no-store'})


@app.get('/print-prod/pdf')
def print_prod_pdf_page(production_date: date | None = None):
    production_date = production_date or date.today()
    try:
        root, output, process = generate_print_prod_pdf(production_date)
    except (PdfGenerationError, ValueError) as exc:
        return PlainTextResponse(f'Unable to generate PDF: {exc}', status_code=503)
    filename = f'DailyProductionReport_{production_date.isoformat()}.pdf'
    return FileResponse(output, media_type='application/pdf', filename=filename,
                        background=BackgroundTask(finish_pdf_process, root, output, process))


@app.get('/print-oee', response_class=HTMLResponse)
def print_oee_page(request: Request, production_date: date | None = None):
    return templates.TemplateResponse(request=request, name='print_oee.html',
                                      context=dict(page_title='PRINT OEE', active_tab='print-oee',
                                                    production_date=production_date or date.today()))


@app.post('/usage/{shift}', response_class=HTMLResponse)
async def save_usage_route(request: Request, shift: str):
    form = await request.form()
    if any(len(form.getlist(key)) != 1 for key in form):
        return JSONResponse({'error':'Duplicate usage fields are not allowed.'},status_code=400)
    try:
        production_date = date.fromisoformat(str(form.get('production_date','')))
    except ValueError:
        return JSONResponse({'error':'Enter a valid Production Date.'},status_code=400)
    raw = {key[len('qty_'):]:value for key,value in form.items() if key.startswith('qty_')}
    def perform_save():
        try:
            with closing(get_connection()) as conn:
                save_usage(conn,production_date,shift,raw)
            return RedirectResponse(f'/usage?production_date={production_date}&saved=true',status_code=303)
        except ValueError as exc:
            return JSONResponse({'error':str(exc)},status_code=400)
        except Exception:
            return JSONResponse({'error':'Unable to save material usage. Nothing was saved.'},status_code=503)
    return await run_in_threadpool(perform_save)
