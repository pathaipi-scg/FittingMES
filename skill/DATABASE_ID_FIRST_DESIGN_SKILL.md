# Database ID-First Design Standard

## Purpose

This document defines the default database design rules for new
FittingMES tables, master data, relationships, migrations, and
application data access. These rules apply to all new modules unless an
existing legacy schema makes them impossible. Any exception must be
identified and reviewed before implementation.

## 1. Mandatory Base Columns for Every New Table

Every newly created table must include these two base columns:

``` sql
id bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,
Rectime datetime NOT NULL DEFAULT (GETDATE())
```

Rules for `id`:

-   Must use `bigint`.
-   Must auto-increment with `IDENTITY(1,1)`.
-   Is the default surrogate primary key for every new table unless an
    exception is explicitly approved.
-   Do not use a name, description, business code, or mutable text as
    the primary relational identity.

Rules for `Rectime`:

-   Must use SQL Server `datetime`.
-   Must be `NOT NULL`.
-   Must default to `GETDATE()`.
-   Represents record creation time unless an explicitly documented
    table requirement says otherwise.
-   Application code should not need to supply the creation timestamp.

Do not silently replace these defaults with `int`, `uniqueidentifier`,
`datetime2`, `SYSDATETIME()`, or another convention unless explicitly
approved.

## 2. ID-First Relational Design

If an authoritative master/entity has an ID, all new relational
references must use that ID.

Examples:

-   Use `ProductFamilyID`, not `ProductFamily`.
-   For a new RejectReason master, use its surrogate ID as the
    relational FK; keep `ReasonCode` such as `R101` as a unique business
    code.
-   Never use Thai/English names or display labels as foreign keys.
-   Do not use mutable text as relational identity.

IDs are opaque. SQL and application logic must never infer business
meaning from a numeric ID.

Bad:

``` sql
WHERE ProductFamilyID = 4 -- assumes ID 4 always means Special Ridge
```

Good: resolve the authoritative row at the boundary, then
store/reference its ID.

## 3. New Master Tables

Every new master table follows the same base-column rule and uses
`id bigint IDENTITY(1,1)` as its surrogate relational identity.

Business codes remain separate unique attributes.

Example:

``` sql
CREATE TABLE dbo.RejectReason
(
    id bigint IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_RejectReason PRIMARY KEY,

    Rectime datetime NOT NULL
        CONSTRAINT DF_RejectReason_Rectime DEFAULT (GETDATE()),

    ReasonCode varchar(10) NOT NULL,
    ReasonNameTH nvarchar(400) NOT NULL,

    CONSTRAINT UQ_RejectReason_ReasonCode UNIQUE (ReasonCode)
);
```

`ReasonCode` is a business/display code, not the relational identity.

## 4. Foreign Keys and JOINs

Before creating a new FK:

1.  Inspect the authoritative master table.
2.  Identify its real primary/surrogate ID.
3.  Reuse that ID.
4.  Do not duplicate the master name/code into a new relational key.
5.  Add a proper FK constraint where compatible with the existing
    schema.

If an existing legacy master has no ID and uses a string/code key:

-   Do not silently redesign it.
-   Do not create a duplicate master merely to obtain an ID.
-   Report the legacy gap first.
-   Propose the safest migration path.
-   Wait for approval before changing a widely referenced legacy key.

## 5. Business Codes, Names, and Snapshots

Text columns are allowed when their purpose is explicit. Classify them
as business code, display text, historical snapshot, external
integration identifier, or unavoidable legacy key.

Historical snapshots such as `ProductFamilySnapshot`,
`ReasonNameSnapshot`, or `SourceNameSnapshot` are allowed when
preserving historical display values is useful.

Snapshot/display text must never become the authoritative source for
JOINs, FK relationships, current validation, business-rule lookup, or
current master identity.

## 6. Master Data and Business Rules Belong in the Database

Configurable business rules must be represented by database
master/configuration data rather than hardcoded lists in Python,
JavaScript, templates, or route handlers.

For REJECT, for example:

-   Reason -\> PRESS/LINE comes from DB master/configuration.
-   Do not infer scope from `R1xx`, `R2xx`, `R3xx`, reason names, code
    ranges, or numeric comparisons.
-   Press/Line membership comes from existing equipment configuration.
-   Product-family applicability uses `ProductFamilyID`.

Application code may implement generic behavior based on database
values, but must not contain a second copy of master mappings.

## 7. Seed and Migration Rules

For seed data that references existing masters:

-   Do not hardcode opaque numeric IDs.
-   Resolve the target row from an authoritative unique business key.
-   Verify exactly one row resolves.
-   Fail safely if zero or multiple rows resolve.
-   Store the resolved ID in the new relational row.

Never edit an already-applied historical migration to introduce a new
design. Create a new migration and matching rollback according to
repository conventions.

## 8. Existing Schema Safety

A new module must not silently trigger a broad redesign of legacy
tables.

Before implementation, audit current PKs/FKs, existing ID columns,
unique business codes, affected references, legacy string-key
dependencies, and existing master/configuration tables that should be
reused.

If an ID already exists, use it. If an ID does not exist, report the gap
before changing the legacy model.

## 9. Application Validation

Server-side validation is authoritative. Browser/UI filtering is for
usability only.

On SAVE, the server must re-read authoritative master/configuration data
and validate relational IDs and current applicability.

Do not trust posted names, labels, source types, product-family names,
or other display text as identity.

## 10. Testing Requirements

Tests should verify as applicable:

-   every new table has `id bigint IDENTITY(1,1)`;
-   every new table has `Rectime datetime NOT NULL DEFAULT GETDATE()`;
-   new relational FKs use authoritative IDs when available;
-   names/display text are not used as relational keys;
-   business codes remain unique where required;
-   opaque numeric IDs are not hardcoded as business meaning;
-   seed scripts resolve IDs safely from authoritative masters;
-   application code does not duplicate configurable DB mappings;
-   server-side validation rejects tampered IDs or invalid
    relationships;
-   historical snapshots are not used as current relational identity;
-   legacy tables/integrations remain unchanged unless explicitly in
    scope.

## 11. Design Review Checklist

Before approving a new table or migration:

1.  Does it have `id bigint IDENTITY(1,1)`?
2.  Does it have `Rectime datetime NOT NULL DEFAULT GETDATE()`?
3.  Is the primary relational identity an ID rather than a name/code?
4.  Do FKs use authoritative IDs wherever IDs exist?
5.  Are business codes separate from relational IDs?
6.  Are names/descriptions display-only or intentional snapshots?
7.  Are any numeric IDs hardcoded with assumed business meaning?
8.  Are configurable business mappings stored in DB
    master/configuration?
9.  Were existing masters audited before creating new ones?
10. Would the migration unexpectedly redesign a legacy table?
11. Are migration, rollback, and tests aligned with these rules?

If any answer violates this standard, stop and report the exception
before implementation.
