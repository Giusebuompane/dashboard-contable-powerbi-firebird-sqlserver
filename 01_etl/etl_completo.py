from firebird.driver import connect as fb_connect
import pandas as pd
from sqlalchemy import create_engine, text
import urllib
import re
import warnings
import logging
from pathlib import Path
from datetime import datetime
import sys
import os
from dotenv import load_dotenv

warnings.filterwarnings("ignore")

# Rutas, servidores y credenciales se leen de un fichero .env que no se sube al repositorio
load_dotenv(Path(__file__).parent / ".env")

# ======================
# LOGGING
# ======================
LOG_DIR = Path(os.getenv("LOG_DIR", Path(__file__).parent / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOG_DIR / f"etl_{datetime.now():%Y-%m-%d}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ETL_CONTABILIDAD")

# ======================
# VARIABLES CONFIGURABLES
# ======================
SERVIDOR_FB = os.getenv("FB_SERVIDOR", "localhost")
PUERTO_FB = os.getenv("FB_PUERTO", "3050")
USER = os.environ["FB_USUARIO"]
PASSWORD = os.environ["FB_PASSWORD"]
CHARSET = "UTF8"

# Carpeta con un subdirectorio por ejercicio: <RUTA_BASE>\<año>\<año>.FDB
RUTA_BASE = os.environ["FB_RUTA_EJERCICIOS"]

# Años a procesar: desde ANIO_INICIO hasta el año actual, generado automáticamente.
# Cuando llegue un año nuevo (ej. 2027) y Microdata aún no lo haya creado, se omite
# limpio (log informativo, no error); en cuanto exista el .FDB, se incluye solo.
ANIO_INICIO = 2023
ANIOS = list(range(ANIO_INICIO, datetime.now().year + 1))

TABLAS_DESTINO = {
    "MAY": "MAY_2026",
    "DIA": "DIA_2026",
    "CLA": "CLA_2026",
}

# Tablas maestras (no son por año, viven en la base MICRO.FDB general)
RUTA_MASTER = os.environ["FB_RUTA_MAESTRO"]
TABLAS_MAESTRAS = ["EMPRESA", "SUJETOS"]

params = urllib.parse.quote_plus(
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={os.getenv('SQL_SERVIDOR', 'localhost')};"
    f"DATABASE={os.getenv('SQL_BASE_DATOS', 'BBDD_PowerBI')};"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)
engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}", fast_executemany=True)

errores = []


def limpiar_saltos(text_val):
    if isinstance(text_val, str):
        return re.sub(r'[\r\n\t]+', ' ', text_val).strip()
    return text_val


def normalizar_dataframe(df):
    for c in df.select_dtypes(include="object").columns:
        df[c] = df[c].apply(limpiar_saltos)
    fecha_cols = [c for c in df.columns if "FECHA" in c.upper()]
    for fc in fecha_cols:
        df[fc] = pd.to_datetime(df[fc], errors="coerce")
    for c in df.select_dtypes(include="object").columns:
        try:
            df[c] = pd.to_numeric(df[c], errors="ignore")
        except Exception:
            pass
    return df


def cargar_prefijo_desde_fdb(db_path, anio, prefijo):
    log.info(f"Cargando año {anio} - prefijo {prefijo}...")
    dfs = []
    try:
        con = fb_connect(db_path, user=USER, password=PASSWORD, charset=CHARSET)
        cur = con.cursor()
        cur.execute("SELECT RDB$RELATION_NAME FROM RDB$RELATIONS WHERE RDB$SYSTEM_FLAG=0")
        all_tables = [r[0].strip() for r in cur.fetchall()]
        tablas_filtradas = [
            t for t in all_tables
            if t.startswith(prefijo) and any(c.isdigit() for c in t)
        ]
        log.info(f"  {anio}/{prefijo}: {len(tablas_filtradas)} tablas encontradas")

        for tbl in tablas_filtradas:
            try:
                cur.execute(f"SELECT * FROM {tbl}")
                cols = [d[0].strip() for d in cur.description]
                rows = cur.fetchall()
                if not rows:
                    continue
                df = pd.DataFrame(rows, columns=cols)
                df = normalizar_dataframe(df)
                df["Año"] = anio
                df["Codigo_empresa"] = int(tbl[-5:])
                dfs.append(df)
            except Exception as e:
                log.error(f"Fallo leyendo tabla {tbl} (año {anio}, prefijo {prefijo}): {e}")
                errores.append({"Año": anio, "Prefijo": prefijo, "Tabla": tbl, "Error": str(e)})

        cur.close()
        con.close()
    except Exception as e:
        log.error(f"Fallo de CONEXIÓN a Firebird para {db_path}: {e}")
        errores.append({"Año": anio, "Prefijo": prefijo, "Tabla": "CONEXION", "Error": str(e)})

    if dfs:
        return pd.concat(dfs, ignore_index=True, sort=False)
    return pd.DataFrame()


def procesar_tabla(prefijo, tabla_sql):
    log.info(f"=== PROCESANDO {prefijo} -> {tabla_sql} ===")
    dfs_prefijo = []

    for anio in ANIOS:
        ruta_local = Path(f"{RUTA_BASE}\\{anio}\\{anio}.FDB")
        if not ruta_local.exists():
            log.info(f"Año {anio} aún no existe en Microdata, se omite.")
            continue

        db_path = f"{SERVIDOR_FB}/{PUERTO_FB}:{RUTA_BASE}\\{anio}\\{anio}.FDB"
        df_anio = cargar_prefijo_desde_fdb(db_path, anio, prefijo)
        if not df_anio.empty:
            dfs_prefijo.append(df_anio)

    if not dfs_prefijo:
        log.warning(f"No se cargaron datos para {prefijo}, se omite {tabla_sql}.")
        return False

    macro_df = pd.concat(dfs_prefijo, ignore_index=True, sort=False)
    total_filas = len(macro_df)
    log.info(f"TOTAL {prefijo}: {total_filas} filas, años: {sorted(macro_df['Año'].unique())}")

    try:
        with engine.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {tabla_sql}"))

        CHUNK = 5000
        for inicio in range(0, total_filas, CHUNK):
            trozo = macro_df.iloc[inicio:inicio + CHUNK]
            trozo.to_sql(tabla_sql, engine, if_exists="append", index=False)
            cargado = min(inicio + CHUNK, total_filas)
            log.info(f"  {tabla_sql}: {cargado}/{total_filas} filas ({cargado*100//total_filas}%)")

        log.info(f"Tabla {tabla_sql} actualizada correctamente ({total_filas} filas).")
        return True
    except Exception as e:
        log.error(f"FALLO al escribir tabla {tabla_sql} en SQL Server: {e}")
        errores.append({"Año": "-", "Prefijo": prefijo, "Tabla": tabla_sql, "Error": str(e)})
        return False


def procesar_tabla_maestra(nombre_tabla):
    log.info(f"=== PROCESANDO TABLA MAESTRA {nombre_tabla} ===")
    db_path = f"{SERVIDOR_FB}/{PUERTO_FB}:{RUTA_MASTER}"
    try:
        con = fb_connect(db_path, user=USER, password=PASSWORD, charset=CHARSET)
        cur = con.cursor()
        cur.execute(f"SELECT * FROM {nombre_tabla}")
        cols = [d[0].strip() for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        con.close()

        if not rows:
            log.warning(f"Tabla maestra {nombre_tabla} sin filas, se omite.")
            return False

        df = pd.DataFrame(rows, columns=cols)
        df = normalizar_dataframe(df)

        df.to_sql(nombre_tabla, engine, if_exists="replace", index=False, chunksize=5000)
        log.info(f"Tabla maestra {nombre_tabla} actualizada correctamente ({len(df)} filas).")
        return True
    except Exception as e:
        log.error(f"FALLO al procesar tabla maestra {nombre_tabla}: {e}")
        errores.append({"Año": "-", "Prefijo": "MASTER", "Tabla": nombre_tabla, "Error": str(e)})
        return False


# ======================
# EJECUCIÓN PRINCIPAL
# ======================
log.info("========== INICIO PROCESO ETL CONTABILIDAD ==========")
log.info(f"Años a procesar: {ANIOS}")
resultado_ok = True

try:
    for prefijo, tabla_sql in TABLAS_DESTINO.items():
        ok = procesar_tabla(prefijo, tabla_sql)
        resultado_ok = resultado_ok and ok

    for tabla_maestra in TABLAS_MAESTRAS:
        ok = procesar_tabla_maestra(tabla_maestra)
        resultado_ok = resultado_ok and ok
except Exception as e:
    log.critical(f"ERROR CRÍTICO, PROCESO INTERRUMPIDO: {e}", exc_info=True)
    resultado_ok = False

if errores:
    err_file = LOG_DIR / f"errores_{datetime.now():%Y-%m-%d}.csv"
    pd.DataFrame(errores).to_csv(err_file, index=False, sep=";", encoding="utf-8")
    log.warning(f"{len(errores)} incidencias registradas en {err_file}")

if resultado_ok and not errores:
    log.info("========== PROCESO FINALIZADO: OK, SIN ERRORES ==========")
    sys.exit(0)
elif resultado_ok and errores:
    log.warning("========== PROCESO FINALIZADO: OK CON AVISOS (ver CSV de errores) ==========")
    sys.exit(0)
else:
    log.critical("========== PROCESO FINALIZADO: CON FALLOS ==========")
    sys.exit(1)
