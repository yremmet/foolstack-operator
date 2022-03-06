import kopf
import kubernetes
import psycopg
import uuid
import base64
import os

def getPostgresConnection():
    port=os.environ['POSTGRES_SERVICE_PORT']
    db=os.environ['POSTGRES_DB']
    host=os.environ['POSTGRES_SERVICE_HOST']
    user=os.environ['POSTGRES_USER']
    password=os.environ['POSTGRES_PASSWORD']
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"

def encode64(str,encoding="utf-8"):
    encoded = base64.b64encode(str.encode("utf-8")).decode("utf-8")
    return encoded

def decode64(str, encoding="utf-8"):
    decoded = base64.b64decode(str).decode(encoding)
    return decoded

def create_secret(namespace, name):
    api = kubernetes.client.CoreV1Api()
    try:
        database, password, username = get_secret(api, name, namespace)
        return username, password, database, database
    except kubernetes.client.exceptions.ApiException as error:
        if error.status != 404:
            raise error
    port = os.environ['POSTGRES_SERVICE_PORT']
    host = os.environ['POSTGRES_SERVICE_HOST']
    username = str(uuid.uuid4()).split('-')[1]
    password = str(uuid.uuid4())
    database = f"{namespace}_{name}"
    secret = kubernetes.client.V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=kubernetes.client.V1ObjectMeta(name="postgres-%s" % name),
        type="Opaque",
        data={"username": encode64(username),
              "password": encode64(password),
              "database": encode64(database),
              "host": encode64(host),
              "port": encode64(port),
              "connection": encode64(f"postgresql://{username}:{password}@{host}:{port}/{database}")
              }
    )

    api.create_namespaced_secret(namespace, secret)
    return username, password, database, database


def get_secret(api, name, namespace):
    secret = api.read_namespaced_secret(f"postgres-{name}", namespace)
    data = secret.data
    username = decode64(data["username"])
    password = decode64(data["password"])
    database = decode64(data["database"])
    return database, password, username


def create_database(cursor, database):
    cursor.execute(f"SELECT datname FROM pg_database where datname = '{database}';")
    recordset = cursor.fetchone()
    if recordset == None:
        cursor.execute(f"CREATE DATABASE \"{database}\" ;")

def create_user(cursor, role, database, username, password):
    # create role
    try:
        cursor.execute(f"SELECT rolname FROM pg_roles where rolname = '{role}';")
    except kubernetes.client.exceptions.ApiException as error:
        if error.status == 404:
            print("Already Gone")
            return

    recordset = cursor.fetchone()
    if recordset == None:
        cursor.execute(f"CREATE ROLE \"{role}\" NOLOGIN;")
        cursor.execute(f"REVOKE ALL ON schema public FROM \"{role}\";")
    # grant access to database
    cursor.execute(f"ALTER DATABASE \"{database}\" OWNER TO \"{role}\";")
    # create user
    cursor.execute(f"SELECT usename FROM pg_catalog.pg_user WHERE usename = '{username}';")
    recordset = cursor.fetchone()
    if recordset == None:
        cursor.execute(f"CREATE USER \"{username}\" with password '{password}';")
        cursor.execute(f"GRANT \"{role}\" TO \"{username}\";")

def delete_secret(namespace, name):
    api = kubernetes.client.CoreV1Api()
    try:
        api.delete_namespaced_secret(namespace=namespace, name="postgres-%s" % name)
    except kubernetes.client.exceptions.ApiException as error:
        if error.status == 404:
            print("Already Gone")
        else:
            raise error

@kopf.on.create('postgresqlservices')
def create_fn(spec, name, namespace, logger, **kwargs):
    username,password,database,role  = create_secret(namespace, name)
    with psycopg.connect(getPostgresConnection()) as con:
        con.autocommit = True
        cur = con.cursor()

        create_database(cur,database)
        create_user(cur,role,database,username,password)

    print(f"A handler is called with body: {spec}")

@kopf.on.delete('postgresqlservices')
def delete_fn(spec, name, namespace, logger, **kwargs):
    api = kubernetes.client.CoreV1Api()
    db_name = f"{namespace}_{name}"
    username= ""
    try:
        db_name, _, username = get_secret(api, name, namespace)
    except kubernetes.client.exceptions.ApiException as error:
        if error.status == 404:
            print("Already Gone")
        else:
            return
    role = db_name
    with psycopg.connect(getPostgresConnection()) as con:
        con.autocommit = True
        cur = con.cursor()
        if username != "":
            ignore_error_execut(cur, f"DROP OWNED BY \"{username}\";")
        ignore_error_execut(cur, f"DROP OWNED BY \"{role}\";")
        ignore_error_execut(cur, f"DROP DATABASE \"{db_name}\";")
        ignore_error_execut(cur, f"REVOKE ALL ON schema public FROM \"{role}\";")
        ignore_error_execut(cur, f"DROP ROLE \"{role}\";")
        if username != "":
            ignore_error_execut(cur, f"REVOKE ALL ON schema public FROM \"{username}\";")
            ignore_error_execut(cur, f"DROP ROLE \"{username}\";")
    delete_secret(namespace,name)
    print("Delete handler is called with name:")

def ignore_error_execut(cursor, sql):
    try:
        cursor.execute(sql)
    except psycopg.errors.UndefinedObject:
        print("Error exectuting "+ sql)
    except psycopg.errors.InvalidCatalogName:
        print("Error exectuting " + sql)