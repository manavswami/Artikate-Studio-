# Django Backend Assessment

## Overview

This repository contains the solution for the Django Backend Assessment.

The project is divided into four independent sections.

- Section 1 – Diagnose a Broken System
- Section 2 – Rate Limited Async Job Queue
- Section 3 – Multi Tenant Data Isolation
- Section 4 – Written Architecture Review 

Each section is organized inside its own application or documentation file.

---

# Project Structure

```
artikate_studio/
│
├── artikate_studio/                # Django project settings
│
├── jobs/                           # Section 2    NOTE VERY IMP : need redis to be install  via docker  and run redis/Start
│                                                  before testing this section
│                                                  
│
├── orders/                         # Section 1
│
├── tenant/                         # Section 3
│
├── architecture_review.md          # Section 4  
│
├── manage.py
├── requirements.txt
├── README.md
└── db.sqlite3
```

---

# Applications

## 1. jobs

The **jobs** application contains the complete implementation of the rate-limited email queue.

### Features

- Celery based asynchronous tasks
- Redis backed queue
- Redis atomic rate limiter
- Dispatcher task
- Exponential backoff retry
- Dead-letter queue
- Queue monitoring commands
- Automated tests

### Folder Structure

```
jobs/
│
├── management/
│   └── commands/
│       ├── clear_email_queue.py
│       ├── queue_demo.py
│       ├── queue_status.py
│       └── test_500_real_jobs.py
│
├── tests/
│   ├── test_dispatcher.py
│   ├── test_job_queue.py
│   ├── test_rate_limiter.py
│   └── test_tasks.py
│
├── pending_queue.py
├── rate_limiter.py
├── tasks.py
│
├── DESIGN.md
└── ANSWERS.md
```

### Documentation

- `jobs/DESIGN.md` explains the architecture and design decisions.
- `jobs/ANSWERS.md` contains answers related to the queue implementation.

---

## 2. orders

The **orders** application is used for the database and ORM-related assessment.

### Folder Structure

```
orders/
│
├── management/
│   └── commands/
│       └── seed_orders.py
│
├── migrations/
│
├── tests/
│   ├── factories.py
│   ├── test_correctness.py
│   └── test_query_performance.py
│
├── admin.py
├── models.py
├── serializers.py
├── service.py
├── urls.py
├── views.py
└── README.md
```

### Documentation

Additional implementation details are available in

```
orders/README.md
```

---

## 3. tenant

The **tenant** application implements automatic tenant isolation.

### Features

- Custom TenantManager
- Automatic queryset filtering
- Request middleware
- Thread-local tenant context

### Folder Structure

```
tenant/
│
├── context.py
├── managers.py
├── middleware.py
├── models.py
├── tenant_models.py
├── tests.py
│
├── README.md
└── ANSWERS.md
```

### Documentation

Implementation details are available in

```
tenant/README.md
```

Written answers are available in

```
tenant/ANSWERS.md
```

---

# Running the Project

## Install Dependencies


```bash
pip install -r requirements.txt
```

---

## Apply Migrations

```bash
python manage.py migrate
```

---

## Run Development Server

```bash
python manage.py runserver
```

---

## Start Celery Worker

```bash
celery -A artikate_studio worker --loglevel=INFO --pool=solo
```

---

# Useful Commands

## Submit Demo Queue

```bash
python manage.py queue_demo --count 500 --fail-once-index 1 --reset
```

---

## Check Queue Status

```bash
python manage.py queue_status --watch --interval 1
```

---

## Clear Email Queue

```bash
python manage.py clear_email_queue --yes
```

---

## Run Queue Integration Test

```bash
python manage.py test_500_real_jobs
```

---

## Run All Tests

```bash
python manage.py test
```

---

## Run Queue Tests

```bash
python manage.py test jobs
```

---

## Run Orders Tests

```bash
python manage.py test orders
```

---

## Run Tenant Tests

```bash
python manage.py test tenant
```

---

# Documentation

The project contains separate documentation for each section.

| File | Description |
|------|-------------|
| README.md | Project overview |
| jobs/DESIGN.md | Queue architecture and design decisions |
| jobs/ANSWERS.md | Queue implementation answers |
| orders/README.md | Orders application details |
| tenant/README.md | Tenant implementation details |
| tenant/ANSWERS.md | Tenant written answers |

---

# Technologies Used

- Python
- Django
- Celery
- Redis
- SQLite
- Django ORM

---

# References

Django Documentation

https://docs.djangoproject.com/

Celery Documentation

https://docs.celeryq.dev/

Redis Documentation

https://redis.io/docs/

Django ORM Documentation

https://docs.djangoproject.com/en/stable/topics/db/queries/

Django Middleware

https://docs.djangoproject.com/en/stable/topics/http/middleware/

Django Managers

https://docs.djangoproject.com/en/stable/topics/db/managers/

Django Testing

https://docs.djangoproject.com/en/stable/topics/testing/