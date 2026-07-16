# Section 4 – Written Architecture Review

## Question A – Django Admin Performance

A database index on the primary key improves row lookups, but it does not solve every performance issue in Django Admin. If an admin page becomes slow with more than 500,000 records, I would investigate the following three areas.

### 1. N+1 Queries

If the admin page displays related fields such as `order.customer.name` or `order.product.name`, Django may execute one additional query for every row displayed. This results in an N+1 query problem.

To fix this, I would override `ModelAdmin.get_queryset()` or use the `list_select_related` option.

```python
class OrderAdmin(admin.ModelAdmin):
    list_select_related = ("customer", "product")
```

For many-to-many relationships, I would use `prefetch_related()` inside `get_queryset()`.

This reduces hundreds of SQL queries into only a few queries and significantly decreases database round trips.

---

### 2. Expensive Model Methods and Calculated Columns

Many Django admin pages display values using custom methods inside `list_display`.

For example:

```python
def total_price(self, obj):
    return obj.items.aggregate(...)
```

This aggregation executes once for every row displayed in the admin.

Instead, I would annotate the queryset inside `get_queryset()`.

```python
queryset = queryset.annotate(total_price=Sum("items__price"))
```

The calculation is then performed once by the database instead of once per object in Python.

---

### 3. Large Result Sets and Counting

By default, Django Admin performs a `COUNT(*)` query to calculate the total number of records for pagination.

On very large tables this query can become expensive.

I would reduce the number of displayed rows using:

```python
list_per_page = 50
```

If exact counts are unnecessary, I would disable the full result count using:

```python
show_full_result_count = False
```

This avoids expensive counting operations while keeping the admin interface responsive.

### Conclusion

The primary key index only optimizes lookups by primary key. In practice, slow Django Admin pages are more commonly caused by excessive ORM queries, expensive per-row computations, and costly pagination counts. Using `list_select_related`, `prefetch_related`, queryset annotations, `list_per_page`, and `show_full_result_count` provides measurable performance improvements while keeping the code maintainable.










---

# Question B – Pagination Trade-offs

Offset-based pagination and cursor-based pagination both solve the problem of limiting the number of records returned by an API, but they have different performance and consistency characteristics.

### Offset-based Pagination

Offset pagination uses SQL clauses such as:

```sql
LIMIT 20 OFFSET 1000;
```

In Django REST Framework, this is implemented using `LimitOffsetPagination` or `PageNumberPagination`.

The main advantage is simplicity. Clients can jump directly to any page, making it suitable for admin dashboards, reporting systems, and applications where users frequently navigate to arbitrary pages.

However, offset pagination performs poorly on very large tables because the database must scan and skip the preceding rows before returning the requested records. Another drawback is inconsistency when data changes between requests. If new records are inserted or existing records are deleted, users may see duplicate records or miss some records while moving between pages.

---

### Cursor-based Pagination

Cursor pagination is implemented in Django REST Framework using `CursorPagination`.

Instead of an offset, it uses a cursor generated from a unique ordered field such as `created_at` or `id`.

The database performs an indexed range scan rather than skipping thousands of rows, making cursor pagination significantly more efficient for large datasets.

Cursor pagination also provides a stable result set. Even if new records are inserted while the client is scrolling, previously viewed records are not duplicated or skipped.

The trade-off is that clients cannot jump directly to page 50 because pagination follows the cursor sequentially.

---

### Which would I choose?

For a mobile application with infinite scrolling, I would choose `CursorPagination` because it scales well and provides consistent results even when data changes frequently.

For internal admin dashboards, reporting interfaces, or applications that require random page access, I would choose `PageNumberPagination` or `LimitOffsetPagination` because users often need to jump directly to specific pages.

In summary, offset pagination offers flexibility but becomes slower and less consistent as datasets grow, while cursor pagination sacrifices random page access in exchange for better scalability and data consistency.





