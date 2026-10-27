# ThriftMap

**Discover thrift stores. Explore sustainable fashion. Find places worth
visiting.**

ThriftMap is a Flask-based web application for discovering thrift and
pre-loved stores in India. It brings store listings, map-based
discovery, community reviews, saved stores, and personalized
recommendations into one place. Store owners can submit and manage
listings, while administrators moderate store submissions and manage
platform users.

> **Project status:** Academic / development project. Run locally and
> use synthetic or otherwise authorized data for demonstrations. A
> public production deployment has not been established by this README.

## Features

### Shopper experience

-   Browse approved thrift-store listings.
-   Search and filter stores by name, city, and category.
-   Explore store locations on an interactive map using Leaflet and
    OpenStreetMap.
-   View store details, including address, contact information, opening
    hours, and location where provided.
-   Register, log in, and manage account preferences.
-   Save stores to favorites.
-   Submit ratings and reviews, and manage your own reviews.

### Store-owner tools

-   Submit store listings with descriptions, contact details, opening
    hours, categories, and coordinates.
-   Upload store images (JPG, JPEG, PNG, and WebP; maximum 5 MB).
-   Manage listings and view reviews for owned stores.
-   Listings require administrator approval before appearing in public
    discovery.

### Administrator tools

-   Review, approve, or reject store submissions.
-   View and manage registered users, including roles and account
    status.
-   View platform reports and store/review metrics.

### Hybrid recommendation engine

The recommendation engine combines several interpretable signals: -
**Content-based relevance:** user category preferences and keyword
overlap with store information. - **Collaborative relevance:**
similarity between users based on observed favorites and ratings. -
**Location relevance:** a soft distance score based on the Haversine
formula. - **Cold-start handling:** recommendations can fall back to
content and location signals when there is not enough collaborative
evidence. - **Visibility rule:** recommendations are restricted to
approved stores.

This is a deterministic hybrid similarity/ranking system, not a
deep-learning or neural-network model.

## Technology stack

-   **Backend:** Python, Flask
-   **Database:** MySQL / compatible MariaDB
-   **Database driver:** `mysql-connector-python`
-   **Frontend:** HTML templates, CSS, JavaScript
-   **Interactive maps:** Leaflet.js and OpenStreetMap
-   **Recommendation logic:** custom Python hybrid recommendation engine
-   **Testing:** Python test scripts

## Project structure

``` text
ThriftMap/
├── app.py
├── config.py
├── recommendation_engine.py
├── requirements.txt
├── thriftmap_schema.sql
├── setup_ml_dev_db.py
├── seed_ml_dev.py
├── test_*.py
├── templates/
├── static/
└── backups/
```

The `backups/` directory contains database backup files. Treat backups
as data exports: inspect them before publishing, and do not commit
private or production user data.

## Requirements

-   Python 3.10 or newer recommended
-   MySQL 5.7+ or a compatible MariaDB version
-   Git (optional, for cloning the repository)

## Local setup

### 1. Clone the repository

``` bash
git clone https://github.com/ph-devadathan/ThriftMap.git
cd ThriftMap
```

### 2. Create and activate a virtual environment

**Windows PowerShell:**

``` powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
```

**Git Bash:**

``` bash
python -m venv venv
source venv/Scripts/activate
```

### 3. Install Python dependencies

``` bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Create the database

1.  Start MySQL or MariaDB.
2.  Open phpMyAdmin or a MySQL client.
3.  Import `thriftmap_schema.sql`. The schema creates the `thriftmap_db`
    database and its tables.
4.  Confirm that the database user has permission to access the
    database.

**Important:** Importing a schema into an existing database may not
reset or update every existing table. Back up important data first and
review the SQL before running it.

### 5. Configure database connection variables

`config.py` reads these environment variables and otherwise defaults to
a local MySQL instance using the `root` account, an empty password, and
database `thriftmap_db`.

Set values for your environment before starting the app. Example for
**Windows PowerShell**:

``` powershell
$env:DB_HOST = "localhost"
$env:DB_USER = "root"
$env:DB_PASSWORD = "your_local_mysql_password"
$env:DB_NAME = "thriftmap_db"
```

Replace the example password with your own local database password. Do
not commit actual credentials.

### 6. Start the application

``` bash
python app.py
```

Open `http://127.0.0.1:5000` in your browser.

The current development entry point runs Flask in debug mode and binds
to localhost. Do not use the development server or debug mode for a
public production deployment.

## Recommendation development database

The repository includes `setup_ml_dev_db.py` and `seed_ml_dev.py` for a
separate recommendation-development database. The seed script explicitly
checks that `DB_NAME` is `thriftmap_ml_dev` before inserting synthetic
demo data.

Use these scripts only after reading them and confirming the database
settings. Do not point development-seeding scripts at a production or
primary database. The seed script may create and remove synthetic
records in its target development database.

## Tests

The repository includes test scripts for store discovery, reviews, saved
stores, admin user management, admin reports, and recommendations.
Review each test's database requirements before running it, especially
if it connects to MySQL.

Run an individual test with:

``` bash
python -m unittest test_recommendation_system.py
```

If a test module is not compatible with `unittest` discovery, follow the
test runner and setup described in that file. Configure a safe test
database before running database-dependent tests.

## Database overview

The schema defines these main tables:

-   `users` --- shopper, owner, and administrator accounts and
    preferences
-   `categories` --- store categories
-   `stores` --- store details, owner, location, and approval status
-   `favorites` --- saved stores
-   `reviews` --- ratings and written feedback

Foreign keys link stores to owners and categories, and link favorites
and reviews to users and stores.

## Security and data hygiene

Before deploying or sharing a public demo:

-   Replace the hard-coded Flask `app.secret_key` in `app.py` with a
    secret loaded from an environment variable; use a long, random value
    and never commit it.
-   Use environment variables or a secret manager for database
    credentials.
-   Do not commit `.env` files, passwords, real customer data, or
    private database dumps.
-   Use a least-privilege database account rather than a database
    administrator account.
-   Turn off Flask debug mode outside local development.
-   Check database backup files for personal data before making the
    repository public.
-   Use HTTPS and review authentication, authorization, input
    validation, and upload handling before production use.


## Contributing

This is currently an individual academic project. If you want to propose
improvements, open an issue or submit a pull request with a clear
description of the change.

## License

No license is currently specified. Unless a license is added, the
repository should not be assumed to grant general permission to reuse,
modify, or redistribute the code.
