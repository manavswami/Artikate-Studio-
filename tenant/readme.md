# Tenant App

## Overview

The `tenant` app provides automatic tenant isolation for Django ORM queries.

The current tenant is resolved by middleware and stored in thread-local storage. A custom `TenantManager` automatically filters all querysets for the current tenant.

---

## Files

```
tenant/
│
├── context.py
├── managers.py
├── middleware.py
├── models.py
└── tests.py
```

---

## Tenant Context

`context.py` stores the current tenant for the lifetime of the request.

Available functions:

```python
set_current_tenant(tenant)

get_current_tenant()

clear_current_tenant()
```

The middleware sets the tenant before processing the request and clears it after the response.

---

## Tenant Manager

`TenantManager` overrides `get_queryset()`.

Instead of writing

```python
Order.objects.filter(
    tenant=current_tenant
)
```

developers can simply write

```python
Order.objects.all()
```

The manager automatically applies

```python
.filter(
    tenant=current_tenant
)
```

If no tenant is available, an empty queryset is returned.

---

## Middleware

The middleware performs the following steps.

1. Read tenant information from the request.
2. Load the tenant from the database.
3. Store the tenant using `set_current_tenant()`.
4. Process the request.
5. Clear the tenant using `clear_current_tenant()`.

The tenant context is always cleared inside a `finally` block.

---

## Request Flow

```
Request
   │
   ▼
TenantMiddleware
   │
   ▼
set_current_tenant()
   │
   ▼
View
   │
   ▼
Order.objects.all()
   │
   ▼
TenantManager
   │
   ▼
Database
   │
   ▼
Current Tenant Records
   │
   ▼
clear_current_tenant()
```

---

## Running Tests

Run all tenant tests.

```bash
python manage.py test tenant
```

Run a specific test file.

```bash
python manage.py test tenant.tests
```

---

## Notes

- Automatic tenant filtering
- Custom `TenantManager`
- Request middleware
- Thread-local tenant context
- Fail-closed behavior using `queryset.none()`