import hashlib
import json
from contextlib import closing
from pathlib import Path
from datetime import date, time
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool
from app.lots import rows, day, read_lots, update_lot, insert_lot, next_running_no

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.database import get_connection
from app.pis_config import PISConfig
from app.usage import read_usage_context, save_usage
from app.prod_api import read_prod_records, build_pis_date_preview, field_mapping, preview_readiness
from app.depallet import (read_context as read_depallet_context, read_reasons as read_depallet_reasons,
                          read_curing_lots, read_daily_work, save_depallet, save_depallet_batch)
from app.products import FAMILIES, lot_prefix, read_products, read_mapping, confirm_mapping, selected_product, month_start
from app.production_data import read_production_data, save_production_data, calculate

app = FastAPI(title="FittingMES", version="0.1.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def read_plans(cursor, production_date):
    cursor.execute("""WITH RankedPlans AS (
        SELECT StartTime, Shift, PlanName, MaterialCode, MaterialName, PlanCount, VersionNo,
            ROW_NUMBER() OVER (
                PARTITION BY StartTime, PlanName
                ORDER BY CAST(VersionNo AS int) DESC
            ) AS VersionRank
        FROM dbo.P_ActivePlan
        WHERE Company = ? AND Plant = ? AND Machine = ? AND StartTime = ?
        )
        SELECT StartTime, Shift, PlanName, MaterialCode, MaterialName, PlanCount, VersionNo
        FROM RankedPlans WHERE VersionRank = 1
        ORDER BY StartTime, Shift, PlanName, MaterialCode""", "CRTC", "30A1", "SB2-3", production_date)
    columns = [c[0] for c in cursor.description]
    plans = [dict(zip(columns, row)) for row in cursor.fetchall()]
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


def production_page(request, plan_id=None, product_code=None, confirm=False,
                    create=False, running_no=None, production_date=None, production_id=None, edit=False, save=False, void=False, production_input=None, data_saved=False, product_family=None, product_choices=None):
    requested_date = production_date
    production_date = production_date or date.today()
    context = dict(families=FAMILIES, product_family=None, product_previews={}, production_data={}, calculated=calculate(None, None), data_saved=data_saved, production_date=production_date, lots=[], current=None, edit=edit, edit_plans=[], plans=[], selected=None, products=[], material_prefix=None,
                   product_code=None, lot=None, error=None, running_no=None, created_lot=None)
    status = 200
    try:
        with closing(get_connection()) as conn:
            cursor = conn.cursor()
            context["lots"] = read_lots(cursor)
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
                        product_family, product_code = confirm_mapping(conn, prefix, product_family, product_code)
                    except ValueError:
                        context.update(product_selection_context(cursor, selected))
                        raise
                mapped = read_mapping(cursor, prefix)
                if mapped:
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
         production_id: int | None = None, edit: bool = False, data_saved: bool = False):
    return production_page(request, plan_id, production_date=production_date, production_id=production_id, edit=edit, data_saved=data_saved)


@app.post("/", response_class=HTMLResponse)
def confirm_product(request: Request, plan_id: str = Form(...), production_date: date = Form(...),
                    neufit: str = Form(""), oriental: str = Form(""),
                    special_ridge: str = Form(""), prestige_common: str = Form("")):
    return production_page(request, plan_id, confirm=True, production_date=production_date,
                           product_choices=[neufit, oriental, special_ridge, prestige_common])


@app.post("/lots", response_class=HTMLResponse)
def create_lot(request: Request, plan_id: str = Form(...), running_no: int = Form(...), production_date: date = Form(...)):
    return production_page(request, plan_id, create=True, running_no=running_no, production_date=production_date)


@app.get("/health")
def health():
    return {"status": "ok", "service": "FittingMES"}


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
                  production_id: int | None = None):
    production_date = production_date or date.today()
    context = dict(page_title="PROD API", active_tab="prod-api", production_date=production_date,
                   records=[], previews=[], selected_id=production_id, error=None, diagnostics=[], group_count=0,
                   preview_all=preview_all, preview_count=0, pis_config=PISConfig.from_environment().diagnostics())
    status = 200
    try:
        with closing(get_connection()) as conn:
            context["records"] = read_prod_records(conn.cursor(), production_date)
        if preview_all or preview_one:
            if not context["records"]:
                context["error"] = "No active Production Lots for this date. Nothing to preview."
            else:
                preview_records = context['records'] if preview_all else [
                    row for row in context['records'] if row['ProductionID'] == production_id]
                if not preview_records:
                    context['error'] = 'Select a Production Lot from this date to preview.'
                    status = 400
                for record in preview_records:
                    mapping = field_mapping(record)
                    context['diagnostics'].append(dict(record=record, mapping=mapping,
                        missing=[item['field'] + (': missing ' + ', '.join(item['missing_sources'])
                                 if item.get('missing_sources') else '') for item in mapping
                                 if item['severity'] == 'required']))
                groups = build_pis_date_preview(preview_records, production_date)
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


@app.get("/reject-api", response_class=HTMLResponse)
def reject_api_page(request: Request, production_date: date | None = None):
    return templates.TemplateResponse(request=request, name="reject_api.html", context=dict(
        page_title="REJECT API", active_tab="reject-api", production_date=production_date or date.today()))


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
