# ANSWERS.md

# Section 3 – Multi-Tenant Data Isolation

## 1. Why use a custom TenantManager?

The goal is to make tenant isolation automatic.

Instead of requiring every developer to remember to write:

```python
Order.objects.filter(tenant=current_tenant)
```

the custom `TenantManager` automatically applies the tenant filter inside `get_queryset()`.

This allows developers to simply write:

```python
Order.objects.all()
```

and only the current tenant's records are returned.

This greatly reduces the risk of accidentally exposing another tenant's data due to a missing `.filter(tenant=...)`.

---

## 2. Why is tenant information stored in thread-local storage?

The middleware determines the current tenant at the beginning of every request.

It stores the tenant in thread-local storage using:

```python
threading.local()
```

The custom `TenantManager` retrieves the tenant from thread-local storage and automatically filters every queryset.

This allows tenant isolation without passing the tenant object through every service, serializer, and ORM query.

---

## 3. Failure modes of thread-local storage

Thread-local storage works correctly for traditional synchronous Django applications because one request is processed by one thread.

However, it is **not safe for asynchronous Django views**.

Async requests share the same thread while switching between multiple coroutines.

Since `threading.local()` stores data per thread rather than per coroutine, tenant information may leak between concurrent async requests.

This can result in one request accidentally reading another tenant's data, breaking tenant isolation.

---

## 4. How would I make it safe for async Django?

For asynchronous Django applications I would replace `threading.local()` with Python's `contextvars`.

`contextvars.ContextVar` stores values per asynchronous execution context rather than per thread.

Each coroutine has its own isolated context, preventing tenant information from leaking between concurrent requests.

The middleware would store the tenant in a `ContextVar`, and `TenantManager` would retrieve the tenant from the same `ContextVar`.

This preserves automatic ORM scoping while remaining safe for async request handling.

---

## 5. Tenant identification

For this assessment, the middleware identifies the tenant using the `X-Tenant` request header.

Example:

```
X-Tenant: Company A
```

This approach keeps the implementation simple and easy to test.

In a production system, the tenant would typically be resolved using one of the following:

- JWT claims
- Request subdomain (for example, `company-a.example.com`)
- API Gateway
- API Key

The tenant resolution mechanism is independent of the automatic ORM scoping performed by the custom manager.

---

## 6. Why does the manager return `queryset.none()` when no tenant exists?

If no tenant is available, returning all rows would expose data belonging to every tenant.

Instead, the manager returns:

```python
queryset.none()
```

This is a **fail-closed** approach.

Returning an empty queryset is much safer than exposing all tenant data if tenant resolution fails.

---

## 7. How automatic tenant isolation works

The request lifecycle is:

```
Incoming Request
        │
        ▼
TenantMiddleware
        │
        ▼
Resolve Tenant
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
TenantManager.get_queryset()
        │
        ▼
Order.objects.filter(tenant=current_tenant)
        │
        ▼
Database
        │
        ▼
Only current tenant's records returned
        │
        ▼
clear_current_tenant()
```

This ensures that tenant filtering is applied automatically to every ORM query using the custom manager.

---

## 8. Trade-offs

### Advantages

- Automatic tenant isolation
- Developers cannot accidentally forget the tenant filter
- Centralized implementation
- Easy to maintain
- Simple to understand

### Limitations

- Thread-local storage is not safe for async Django.
- Raw SQL queries bypass the custom manager.
- Queries executed using another manager or `_base_manager` are not automatically scoped.
- PostgreSQL Row-Level Security (RLS) provides stronger enforcement for highly secure multi-tenant systems.

For this assessment, the custom `TenantManager` provides a clean and maintainable ORM-level solution while keeping the implementation simple.