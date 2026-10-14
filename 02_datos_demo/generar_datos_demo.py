"""
Genera datos contables ficticios con la misma estructura que las tablas que la ETL
deja en SQL Server (DIA_2026, MAY_2026, CLA_2026, EMPRESA y SUJETOS) y los carga en
una base de datos SQL Server para poder actualizar el informe de Power BI sin usar
datos reales.

Las empresas, clientes, proveedores, NIF e importes son inventados. Los asientos sí
siguen las reglas contables que usan las medidas del informe: facturas con IVA,
cobros y pagos, nóminas, asientos trimestrales "CIERRE IVA" contra 475/470,
devoluciones de AEAT, regularización (TIPO PERD) y cierre de ejercicio (TIPO CIER).

Uso:
    python generar_datos_demo.py                      -> genera los CSV en ./csv
    python generar_datos_demo.py --cargar             -> además los carga en SQL Server
    python generar_datos_demo.py --cargar --servidor localhost --base BBDD_PowerBI
"""

import argparse
import calendar
import csv
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

SEMILLA = 2026
ANIO_INICIO = 2023
CARPETA_CSV = Path(__file__).parent / "csv"

# ======================
# CATÁLOGO DE CUENTAS (PGC, 12 dígitos como en Microdata)
# ======================
CUENTAS = {
    100000000000: "CAPITAL SOCIAL",
    129000000000: "RESULTADO DEL EJERCICIO",
    170000000000: "DEUDAS A LARGO PLAZO CON ENTIDADES DE CREDITO",
    211000000000: "CONSTRUCCIONES",
    218000000000: "ELEMENTOS DE TRANSPORTE",
    281000000000: "AMORTIZACION ACUMULADA INMOVILIZADO MATERIAL",
    300000000000: "MERCADERIAS",
    465000000000: "REMUNERACIONES PENDIENTES DE PAGO",
    470000000000: "HACIENDA PUBLICA DEUDORA POR IVA",
    470900000000: "HACIENDA PUBLICA DEUDORA POR DEVOLUCION DE IMPUESTOS",
    472000000000: "HACIENDA PUBLICA IVA SOPORTADO",
    473000000000: "HACIENDA PUBLICA RETENCIONES Y PAGOS A CUENTA",
    475000000000: "HACIENDA PUBLICA ACREEDORA POR IVA",
    475100000000: "HACIENDA PUBLICA ACREEDORA POR RETENCIONES PRACTICADAS",
    476000000000: "ORGANISMOS DE LA SEGURIDAD SOCIAL ACREEDORES",
    477000000000: "HACIENDA PUBLICA IVA REPERCUTIDO",
    572000000001: "BANCO CUENTA CORRIENTE",
    600000000000: "COMPRAS DE MERCADERIAS",
    601000000000: "COMPRAS DE MATERIAS PRIMAS",
    602000000000: "COMPRAS DE OTROS APROVISIONAMIENTOS",
    607000000000: "TRABAJOS REALIZADOS POR OTRAS EMPRESAS",
    610000000000: "VARIACION DE EXISTENCIAS DE MERCADERIAS",
    621000000000: "ARRENDAMIENTOS Y CANONES",
    622000000000: "REPARACIONES Y CONSERVACION",
    623000000000: "SERVICIOS DE PROFESIONALES INDEPENDIENTES",
    624000000000: "TRANSPORTES",
    625000000000: "PRIMAS DE SEGUROS",
    626000000000: "SERVICIOS BANCARIOS Y SIMILARES",
    627000000000: "PUBLICIDAD, PROPAGANDA Y RELACIONES PUBLICAS",
    628000000000: "SUMINISTROS",
    629000000000: "OTROS SERVICIOS",
    631000000000: "OTROS TRIBUTOS",
    640000000000: "SUELDOS Y SALARIOS",
    642000000000: "SEGURIDAD SOCIAL A CARGO DE LA EMPRESA",
    662000000000: "INTERESES DE DEUDAS",
    669000000000: "OTROS GASTOS FINANCIEROS",
    681000000000: "AMORTIZACION DEL INMOVILIZADO MATERIAL",
    700000000000: "VENTAS DE MERCADERIAS",
    705000000000: "PRESTACIONES DE SERVICIOS",
    752000000000: "INGRESOS POR ARRENDAMIENTOS",
    759000000000: "INGRESOS POR SERVICIOS DIVERSOS",
}

# ======================
# EMPRESAS FICTICIAS
# ======================
# ventas: facturación media mensual; compras: % de las ventas que se compra;
# iva: tipo de IVA de las ventas (0 = actividad exenta); centros: claves analíticas (CLA)
EMPRESAS = [
    dict(codigo=101, nombre="ALFA DISTRIBUCIONES DEMO SL", nif="B00000101", poblacion="MADRID",
         cuenta_venta=700000000000, ventas=160000, compras=(600000000000, 0.68), iva=0.21,
         empleados=9, alquiler=3800, prestamo=180000, temporada="plana", crecimiento=0.06,
         centros={100: "ALMACEN CENTRAL", 200: "DELEGACION PONIENTE", 300: "VENTA ONLINE"}),
    dict(codigo=102, nombre="BETA TALLERES DEMO SL", nif="B00000102", poblacion="ZARAGOZA",
         cuenta_venta=705000000000, ventas=38000, compras=(601000000000, 0.30), iva=0.21,
         empleados=6, alquiler=2100, prestamo=0, temporada="plana", crecimiento=0.03, centros={}),
    dict(codigo=103, nombre="GAMMA RESTAURACION DEMO SL", nif="B00000103", poblacion="VALENCIA",
         cuenta_venta=700000000000, ventas=52000, compras=(600000000000, 0.34), iva=0.10,
         empleados=6, alquiler=2900, prestamo=60000, temporada="verano", crecimiento=0.04,
         centros={100: "LOCAL PLAZA MAYOR", 200: "TERRAZA PASEO MARITIMO"}),
    dict(codigo=104, nombre="DELTA CONSULTORES DEMO SLP", nif="B00000104", poblacion="SEVILLA",
         cuenta_venta=705000000000, ventas=31000, compras=(607000000000, 0.15), iva=0.21,
         empleados=4, alquiler=1500, prestamo=0, temporada="consultora", crecimiento=0.08, centros={}),
    dict(codigo=105, nombre="EPSILON INMUEBLES DEMO SL", nif="B00000105", poblacion="MURCIA",
         cuenta_venta=752000000000, ventas=26000, compras=None, iva=0.21,
         empleados=1, alquiler=0, prestamo=650000, temporada="plana", crecimiento=0.02,
         centros={100: "INMUEBLE 01 - LOCAL C/ OLIVO", 200: "INMUEBLE 02 - NAVE POLIGONO SUR",
                  300: "INMUEBLE 03 - OFICINAS CENTRO", 400: "INMUEBLE 04 - APARTAMENTOS PLAYA"}),
    dict(codigo=106, nombre="ZETA FERRETERIA DEMO SL", nif="B00000106", poblacion="VALLADOLID",
         cuenta_venta=700000000000, ventas=70000, compras=(600000000000, 0.63), iva=0.21,
         empleados=5, alquiler=2400, prestamo=90000, temporada="primavera", crecimiento=-0.02,
         centros={100: "TIENDA", 200: "ALMACEN"}),
    dict(codigo=107, nombre="ETA CLINICA DENTAL DEMO SLP", nif="B00000107", poblacion="BILBAO",
         cuenta_venta=705000000000, ventas=47000, compras=(602000000000, 0.12), iva=0.0,
         empleados=8, alquiler=3100, prestamo=120000, temporada="plana", crecimiento=0.05, centros={}),
    dict(codigo=108, nombre="THETA TRANSPORTES DEMO SL", nif="B00000108", poblacion="PALMA",
         cuenta_venta=705000000000, ventas=72000, compras=(602000000000, 0.27), iva=0.21,
         empleados=10, alquiler=1800, prestamo=240000, temporada="campaña", crecimiento=0.07,
         centros={}, camiones={(2025, 11): 360000, (2026, 2): 420000}, devolucion_is={2025: 4380.55}),
]

TEMPORADAS = {
    "plana":      [1.0, 0.95, 1.0, 1.0, 1.02, 1.0, 1.05, 0.9, 1.0, 1.03, 1.0, 1.05],
    "verano":     [0.6, 0.6, 0.75, 0.9, 1.0, 1.25, 1.6, 1.75, 1.2, 0.9, 0.65, 0.8],
    "primavera":  [0.8, 0.85, 1.1, 1.2, 1.25, 1.1, 0.95, 0.75, 1.0, 1.05, 0.95, 1.0],
    "consultora": [1.1, 1.0, 1.15, 1.25, 0.95, 1.1, 0.85, 0.45, 1.0, 1.1, 1.05, 1.0],
    "campaña":    [1.25, 1.2, 1.15, 1.05, 0.85, 0.7, 0.65, 0.6, 0.85, 1.15, 1.3, 1.25],
}

SILABAS = ["AL", "BA", "CAR", "DO", "MI", "RA", "TOR", "VEN", "LI", "SO", "NA", "GUI",
           "MER", "TA", "LO", "CE", "RI", "PA", "VA", "NE", "QUI", "DEL"]
FORMAS = ["COMERCIAL", "SUMINISTROS", "SERVICIOS", "DISTRIBUCIONES", "GRUPO", "HOSTELERIA",
          "CONSTRUCCIONES", "AGRICOLA", "TALLERES", "LOGISTICA", "INSTALACIONES", "INVERSIONES"]

# ======================
# ESTRUCTURA DE LAS TABLAS (igual que en BBDD_PowerBI)
# ======================
COLUMNAS_DIA = ["ASIENTO", "FECHA", "EPIGRAFE", "CUENTA", "DH", "CONCEPTO", "DEBE", "HABER", "CLAVE",
                "TIPO", "CODASIEN", "CODREGIS", "ESTADO", "PUNTEO", "CODNOTA", "CLAVEMEM", "TEXTO1",
                "TEXTO2", "COBRO347", "NLINEA", "APLI", "Año", "Codigo_empresa"]
MESES_MAY = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
             "SEPTIEM", "OCTUBRE", "NOVIEM", "DICIEM"]
COLUMNAS_MAY = (["CODIGO", "TITULO", "NOTAS", "DEBEINI", "HABERINI", "DEBEACU", "HABERACU"]
                + [p + m for m in MESES_MAY for p in ("D", "H")]
                + ["TIPO", "NIF", "SEXISTEN", "DESCRIP", "DESCRIPCION_SII", "Año", "Codigo_empresa"])
COLUMNAS_CLA = ["CLAVE", "DESCRIP", "BAJA", "Año", "Codigo_empresa"]

# Tipos SQL de cada columna. Las de EMPRESA y SUJETOS coinciden con los tipos del modelo,
# porque en Power Query solo se tipa la columna clave y el resto hereda el tipo de SQL Server.
TIPOS_SQL = {
    "DIA_2026": dict(ASIENTO="INT", FECHA="DATETIME", EPIGRAFE="FLOAT", CUENTA="FLOAT", DEBE="FLOAT",
                     HABER="FLOAT", CODASIEN="FLOAT", CODREGIS="FLOAT", NLINEA="INT", Año="INT",
                     Codigo_empresa="INT"),
    "MAY_2026": dict(CODIGO="BIGINT", Año="INT", Codigo_empresa="INT", SEXISTEN="FLOAT",
                     **{c: "FLOAT" for c in COLUMNAS_MAY[3:31]}),
    "CLA_2026": dict(CLAVE="INT", BAJA="FLOAT", Año="INT", Codigo_empresa="INT"),
}
COLUMNAS_EMPRESA = {
    "CC": "INT", "DOMICILIO": "", "NUMERO": "", "ESCALERA": "", "PISO": "", "PUERTA": "", "CP": "",
    "VIA": "", "POBLACION": "", "PROVINCIA": "", "TELEF1": "", "FALTA": "DATETIME", "FBAJA": "DATETIME",
    "MESINI": "", "ANOINI": "", "RESPON": "", "SOCIOS": "", "BANCO1": "", "BANCO2": "", "BANCO3": "",
    "CC1": "", "CC2": "", "CC3": "", "TIPO": "", "FECHCON": "DATETIME", "NUMCON": "", "NOTCON": "",
    "REGCON": "", "FOLCON": "", "TOMCON": "", "HOJCON": "", "FECHPOD": "DATETIME", "NUMPOD": "",
    "NOTPOD": "", "FOLPOD": "", "TOMPOD": "", "HOJPOD": "", "CAPIPOD": "FLOAT", "CAPAPOD": "FLOAT",
    "ACCIPOD": "FLOAT", "ACCAPOD": "FLOAT", "CODADMI": "", "ADMINIS": "", "DELEGAC": "", "MONEDA": "",
    "PLANTILLA": "", "TIPOPLANT": "", "CREARCALEN": "", "SUBCUEN1": "", "SUBCUEN2": "", "SUBCUEN3": "",
    "TIPOEMP": "", "MICROEMPRESA": "", "OBJETOSOCIAL": "", "CODRESPONSABLE": "", "CODMUNI": "",
    "IDVIA": "INT", "LEI": "", "IRUS": "",
}
COLUMNAS_SUJETOS = {
    "CODIGO": "INT", "NIF": "", "NOMBRE": "", "NOMBCOM": "", "DOMICILIO": "", "CP": "", "VIA": "",
    "POBLACION": "", "NUMERO": "", "ESCALERA": "", "PISO": "", "PUERTA": "", "PROVINCIA": "",
    "TELEF1": "", "TELEF2": "", "TELEF3": "", "FAX": "", "TIPO1": "", "TIPO2": "", "TIPO3": "",
    "TIPO4": "", "TIPO5": "", "TIPO6": "", "TEXTO": "", "ME": "", "CODEMP": "", "CLAEMP": "",
    "CODPRO": "", "CLAPRO": "", "CLASUJ": "", "TIPONIF": "", "TIPOSUJ": "", "NOMBRELARG": "",
    "CORREO": "", "WEB": "", "NOMBRE2": "", "ORIGEN": "", "RESPONSABL": "", "TIPO": "",
    "VIGDESDE": "DATETIME", "VIGHASTA": "DATETIME", "RESTRICCIO": "", "ANAGRAMA": "", "OCULTO": "",
    "INCOMPLETO": "", "CODMUNI": "", "ID": "INT", "IDIDIOMA": "INT", "IDNACIONALIDAD": "INT",
    "DIRECCION": "", "IDVIA": "INT", "EMAILS": "",
}


def r2(x):
    return round(x + 1e-9, 2)


def nombre_inventado(rng, usados):
    while True:
        nombre = f"{rng.choice(FORMAS)} {''.join(rng.choice(SILABAS) for _ in range(rng.choice([2, 3])))} SL"
        if nombre not in usados:
            usados.add(nombre)
            return nombre


def dia_laborable(rng, anio, mes, desde=1):
    ultimo = calendar.monthrange(anio, mes)[1]
    for _ in range(20):
        d = date(anio, mes, rng.randint(desde, ultimo))
        if d.weekday() < 5:
            return d
    return date(anio, mes, ultimo)


class Contabilidad:
    """Diario de una empresa: numera asientos por ejercicio y lleva los saldos de cada cuenta."""

    def __init__(self, empresa, hasta):
        self.e = empresa
        self.hasta = hasta
        self.filas = []
        self.saldos = defaultdict(float)  # debe - haber acumulado (incluye el saldo inicial implícito)
        self.apertura = {}  # saldo inicial implícito, que no aparece en DIA
        self.num_asiento = defaultdict(int)
        self.titulos = {}

    def asiento(self, fecha, concepto, lineas, tipo=""):
        """lineas: lista de (cuenta, debe, haber, clave). Descarta el asiento si es posterior a la fecha de corte."""
        if fecha > self.hasta:
            return False
        lineas = [(c, r2(d), r2(h), k) for c, d, h, k in lineas if r2(d) or r2(h)]
        if not lineas:
            return False
        # Los céntimos que se pierden al redondear cada línea se ajustan en la última
        descuadre = r2(sum(d for _, d, _, _ in lineas) - sum(h for _, _, h, _ in lineas))
        assert abs(descuadre) < 0.1, f"Asiento descuadrado ({descuadre}): {concepto}"
        if descuadre:
            c, d, h, k = lineas[-1]
            lineas[-1] = (c, d, r2(h + descuadre), k) if h else (c, r2(d - descuadre), h, k)
        self.num_asiento[fecha.year] += 1
        for n, (cuenta, debe, haber, clave) in enumerate(lineas, start=1):
            self.saldos[cuenta] += debe - haber
            self.filas.append({
                "ASIENTO": self.num_asiento[fecha.year], "FECHA": fecha, "EPIGRAFE": float(str(cuenta)[:3]),
                "CUENTA": float(cuenta), "DH": "D" if debe else "H", "CONCEPTO": concepto,
                "DEBE": debe, "HABER": haber, "CLAVE": str(clave) if clave else "", "TIPO": tipo,
                "CODASIEN": 0.0, "CODREGIS": float(self.num_asiento[fecha.year]), "ESTADO": "",
                "PUNTEO": "", "CODNOTA": "", "CLAVEMEM": "", "TEXTO1": "", "TEXTO2": "",
                "COBRO347": "N", "NLINEA": n, "APLI": "Z", "Año": fecha.year,
                "Codigo_empresa": self.e["codigo"],
            })
        return True

    def saldos_a_fecha(self, fecha):
        """Saldo de cada cuenta a una fecha, sin contar los asientos de cierre (la apertura no está en DIA)."""
        saldos = defaultdict(float, self.apertura)
        for f in self.filas:
            if f["FECHA"] <= fecha and f["TIPO"] != "CIER":
                saldos[int(f["CUENTA"])] += f["DEBE"] - f["HABER"]
        return saldos


def generar_empresa(e, hasta, rng):
    conta = Contabilidad(e, hasta)
    usados = set()

    # Subcuentas de clientes (430), proveedores (400) y acreedores (410) con nombres inventados
    clientes = {430000000001 + i: nombre_inventado(rng, usados) for i in range(rng.randint(14, 30))}
    proveedores = {400000000001 + i: nombre_inventado(rng, usados) for i in range(rng.randint(8, 16))}
    acreedores = {410000000001: "INMOBILIARIA ARRENDADORA DEMO SL", 410000000002: "ASESORIA LABORAL DEMO SL",
                  410000000003: "COMPAÑIA ELECTRICA DEMO SA", 410000000004: "ASEGURADORA DEMO SA",
                  410000000005: "AGENCIA DE PUBLICIDAD DEMO SL", 410000000006: "MANTENIMIENTOS DEMO SL"}
    conta.titulos.update(CUENTAS)
    conta.titulos.update(clientes)
    conta.titulos.update(proveedores)
    conta.titulos.update(acreedores)
    peso_clientes = [1 / (i + 1) ** 1.1 for i in range(len(clientes))]
    peso_proveedores = [1 / (i + 1) ** 0.9 for i in range(len(proveedores))]

    # Saldo inicial implícito (DIA no trae asiento de apertura, igual que en Microdata)
    inmuebles = e["prestamo"] * 1.2 if e["prestamo"] > 300000 else 0
    capital = 60000 + e["ventas"] * 1.5 + inmuebles * 0.25
    conta.saldos[572000000001] += capital + e["prestamo"] - inmuebles
    conta.saldos[100000000000] -= capital
    conta.saldos[170000000000] -= e["prestamo"]
    conta.saldos[211000000000] += inmuebles
    conta.apertura = dict(conta.saldos)

    centros = list(e["centros"]) or [None]
    iva_comp = 0.0  # IVA a compensar en 4700 (trimestres negativos del ejercicio)

    for anio in range(ANIO_INICIO, hasta.year + 1):
        factor_anio = (1 + e["crecimiento"]) ** (anio - ANIO_INICIO) * rng.uniform(0.93, 1.07)
        iva_trim = defaultdict(lambda: [0.0, 0.0])  # trimestre -> [repercutido, soportado]

        for mes in range(1, 13):
            if date(anio, mes, 1) > hasta:
                break
            trimestre = (mes - 1) // 3 + 1
            venta_mes = e["ventas"] * TEMPORADAS[e["temporada"]][mes - 1] * factor_anio * rng.uniform(0.85, 1.15)

            # Ventas a clientes y su cobro
            n_fact = rng.randint(10, 22)
            for importe in [venta_mes * w for w in _repartos(rng, n_fact)]:
                fecha = dia_laborable(rng, anio, mes)
                cliente = rng.choices(list(clientes), peso_clientes)[0]
                base, iva = r2(importe), r2(importe * e["iva"])
                clave = rng.choice(centros)
                lineas = [(cliente, base + iva, 0, None), (e["cuenta_venta"], 0, base, clave)]
                if iva:
                    lineas.append((477000000000, 0, iva, None))
                if conta.asiento(fecha, f"N/FRA. {anio}/{conta.num_asiento[anio] + 1:05d}", lineas):
                    iva_trim[trimestre][0] += iva
                    cobro = fecha + timedelta(days=rng.choice([0, 15, 30, 30, 45, 60, 90]))
                    if rng.random() > 0.03:
                        conta.asiento(cobro, f"COBRO {clientes[cliente][:25]}",
                                      [(572000000001, base + iva, 0, None), (cliente, 0, base + iva, None)])

            # Compras a proveedores y su pago
            if e["compras"]:
                cuenta_compra, ratio = e["compras"]
                for importe in [venta_mes * ratio * w for w in _repartos(rng, rng.randint(3, 8))]:
                    fecha = dia_laborable(rng, anio, mes)
                    prov = rng.choices(list(proveedores), peso_proveedores)[0]
                    base = r2(importe)
                    iva = r2(base * 0.21) if e["iva"] else 0  # actividad exenta: IVA no deducible, va a gasto
                    if not e["iva"]:
                        base = r2(base * 1.21)
                    lineas = [(cuenta_compra, base, 0, rng.choice(centros)), (prov, 0, base + iva, None)]
                    if iva:
                        lineas.append((472000000000, iva, 0, None))
                    if conta.asiento(fecha, f"S/FRA. {proveedores[prov][:25]}", lineas):
                        iva_trim[trimestre][1] += iva
                        pago = fecha + timedelta(days=rng.choice([30, 45, 60, 60, 90]))
                        conta.asiento(pago, f"PAGO {proveedores[prov][:25]}",
                                      [(prov, base + iva, 0, None), (572000000001, 0, base + iva, None)])

            # Gastos de explotación (grupo 62) a acreedores, pagados por banco
            gastos = [
                (621000000000, 410000000001, e["alquiler"], "ALQUILER LOCAL"),
                (628000000000, 410000000003, venta_mes * rng.uniform(0.012, 0.03), "SUMINISTRO ELECTRICO"),
                (623000000000, 410000000002, 180 + e["empleados"] * 22, "ASESORIA LABORAL Y CONTABLE"),
                (629000000000, 410000000006, venta_mes * rng.uniform(0.004, 0.01), "MATERIAL DE OFICINA"),
            ]
            if rng.random() < 0.35:
                gastos.append((622000000000, 410000000006, venta_mes * rng.uniform(0.01, 0.05), "REPARACION"))
            if rng.random() < 0.25:
                gastos.append((627000000000, 410000000005, venta_mes * rng.uniform(0.01, 0.03), "CAMPAÑA PUBLICIDAD"))
            if mes == 1:
                gastos.append((625000000000, 410000000004, venta_mes * 0.06, "PRIMA SEGURO ANUAL"))
            for cuenta, acreedor, importe, concepto in gastos:
                if importe <= 0:
                    continue
                fecha = dia_laborable(rng, anio, mes)
                base = r2(importe)
                exento = cuenta == 625000000000 or not e["iva"]
                iva = 0 if exento else r2(base * 0.21)
                if not e["iva"] and cuenta != 625000000000:
                    base = r2(base * 1.21)
                lineas = [(cuenta, base, 0, rng.choice(centros)), (acreedor, 0, base + iva, None)]
                if iva:
                    lineas.append((472000000000, iva, 0, None))
                if conta.asiento(fecha, concepto, lineas):
                    iva_trim[trimestre][1] += iva
                    conta.asiento(fecha, f"PAGO {concepto}",
                                  [(acreedor, base + iva, 0, None), (572000000001, 0, base + iva, None)])

            # Compra de vehículos (genera trimestres con IVA a compensar/devolver)
            if (anio, mes) in e.get("camiones", {}):
                base = e["camiones"][(anio, mes)]
                fecha = dia_laborable(rng, anio, mes)
                if conta.asiento(fecha, "S/FRA. VEHICULOS INDUSTRIALES",
                                 [(218000000000, base, 0, None), (472000000000, base * 0.21, 0, None),
                                  (572000000001, 0, base * 1.21, None)]):
                    iva_trim[trimestre][1] += r2(base * 0.21)

            # Nómina mensual (paga extra en junio y diciembre)
            if e["empleados"]:
                fin_mes = date(anio, mes, calendar.monthrange(anio, mes)[1])
                bruto = e["empleados"] * 1850 * factor_anio ** 0.5 * (2 if mes in (6, 12) else 1) * rng.uniform(0.97, 1.03)
                ss_empresa, ss_trab, irpf = bruto * 0.31, bruto * 0.0635, bruto * 0.12
                neto = bruto - ss_trab - irpf
                if conta.asiento(fin_mes, f"NOMINAS {MESES_MAY[mes - 1]} {anio}",
                                 [(640000000000, bruto, 0, None), (642000000000, ss_empresa, 0, None),
                                  (475100000000, 0, irpf, None), (476000000000, 0, ss_empresa + ss_trab, None),
                                  (465000000000, 0, neto, None)]):
                    conta.asiento(fin_mes, "PAGO NOMINAS", [(465000000000, r2(neto), 0, None),
                                                            (572000000001, 0, r2(neto), None)])
                    pago_ss = date(anio + (mes == 12), mes % 12 + 1, 28)
                    conta.asiento(pago_ss, "PAGO SEGUROS SOCIALES",
                                  [(476000000000, r2(ss_empresa) + r2(ss_trab), 0, None),
                                   (572000000001, 0, r2(ss_empresa) + r2(ss_trab), None)])

            # Gastos financieros del préstamo y comisiones
            if e["prestamo"]:
                interes = e["prestamo"] * 0.045 / 12 * (1 - (anio - ANIO_INICIO) * 0.12)
                conta.asiento(date(anio, mes, 5), "LIQUIDACION INTERESES PRESTAMO",
                              [(662000000000, interes, 0, None), (572000000001, 0, interes, None)])
            comision = rng.uniform(15, 60)
            conta.asiento(date(anio, mes, calendar.monthrange(anio, mes)[1]), "COMISIONES BANCARIAS",
                          [(669000000000, comision, 0, None), (572000000001, 0, comision, None)])

            # Fin de trimestre: asiento "CIERRE IVA nT AAAA" y pago de retenciones
            if mes % 3 == 0 and e["iva"]:
                rep, sop = iva_trim[trimestre]
                resultado = r2(rep - sop)
                fin_trim = date(anio, mes, calendar.monthrange(anio, mes)[1])
                lineas = [(477000000000, rep, 0, None), (472000000000, 0, sop, None)]
                a_pagar = 0.0
                if resultado >= 0:
                    compensa = min(resultado, iva_comp)
                    a_pagar = resultado - compensa
                    if compensa:
                        lineas.append((470000000000, 0, compensa, None))
                        iva_comp -= compensa
                    lineas.append((475000000000, 0, a_pagar, None))
                else:
                    lineas.append((470000000000, -resultado, 0, None))
                    iva_comp += -resultado
                if conta.asiento(fin_trim, f"CIERRE IVA {trimestre}T {anio}", lineas):
                    pago = date(anio + (mes == 12), mes % 12 + 1, 20)
                    if a_pagar > 0:
                        conta.asiento(pago, f"PAGO MODELO 303 {trimestre}T {anio}",
                                      [(475000000000, a_pagar, 0, None), (572000000001, 0, a_pagar, None)])
                    if mes == 12 and iva_comp > 0:
                        # En el 4T se pide la devolución del IVA pendiente de compensar; AEAT paga meses después
                        cobro = date(anio + 1, 5, rng.randint(8, 25))
                        conta.asiento(cobro, "AEAT DEVOLUCIONES TRIBUTARIAS",
                                      [(572000000001, iva_comp, 0, None), (470000000000, 0, iva_comp, None)])
                        iva_comp = 0.0
            if mes % 3 == 0 and e["empleados"]:
                retenciones = r2(conta.saldos[475100000000] * -1)
                pago = date(anio + (mes == 12), mes % 12 + 1, 20)
                conta.asiento(pago, f"PAGO MODELO 111 {trimestre}T {anio}",
                              [(475100000000, retenciones, 0, None), (572000000001, 0, retenciones, None)])

        # Fin de ejercicio (solo años cerrados)
        if date(anio, 12, 31) < hasta and anio < hasta.year:
            cierre = date(anio, 12, 31)
            if e["prestamo"] > 300000 or "camiones" in e:
                conta.asiento(cierre, "AMORTIZACION INMOVILIZADO",
                              [(681000000000, e["prestamo"] * 0.03 + 4000, 0, None),
                               (281000000000, 0, e["prestamo"] * 0.03 + 4000, None)])
            if e["compras"] and e["compras"][0] == 600000000000:
                variacion = r2(e["ventas"] * rng.uniform(-0.25, 0.25))
                conta.asiento(cierre, "VARIACION DE EXISTENCIAS",
                              [(300000000000, max(variacion, 0), max(-variacion, 0), None),
                               (610000000000, max(-variacion, 0), max(variacion, 0), None)])
            if anio in e.get("devolucion_is", {}):
                importe = e["devolucion_is"][anio]
                conta.asiento(cierre, f"IMPUESTO SOCIEDADES {anio} A DEVOLVER",
                              [(470900000000, importe, 0, None), (473000000000, 0, importe, None)])
                conta.asiento(date(anio + 1, 7, 18), "AEAT DEVOLUCION IMPUESTO SOCIEDADES",
                              [(572000000001, importe, 0, None), (470900000000, 0, importe, None)])

            # Regularización: grupos 6 y 7 contra la 129 (TIPO PERD)
            saldos = conta.saldos_a_fecha(cierre)
            lineas, resultado = [], 0.0
            for cuenta in sorted(saldos):
                saldo = r2(saldos[cuenta])
                if str(cuenta)[0] in "67" and saldo:
                    lineas.append((cuenta, max(-saldo, 0), max(saldo, 0), None))
                    resultado += saldo
            lineas.append((129000000000, max(r2(resultado), 0), max(-r2(resultado), 0), None))
            conta.asiento(cierre, "REGULARIZACION", lineas, tipo="PERD")

            # Cierre: deja a cero las cuentas de balance a 31/12 (TIPO CIER). No se genera el asiento de
            # apertura del año siguiente porque DIA tampoco lo trae.
            saldos = conta.saldos_a_fecha(cierre)
            lineas = []
            for cuenta in sorted(saldos):
                saldo = r2(saldos[cuenta])
                if str(cuenta)[0] in "12345" and saldo:
                    lineas.append((cuenta, max(-saldo, 0), max(saldo, 0), None))
            conta.asiento(cierre, "ASIENTO DE CIERRE", lineas, tipo="CIER")
    return conta


def _repartos(rng, n):
    pesos = [rng.lognormvariate(0, 0.6) for _ in range(n)]
    total = sum(pesos)
    return [p / total for p in pesos]


def construir_may(conta, e):
    """Plan de cuentas por ejercicio con sumas mensuales, como la tabla MAY de Microdata."""
    filas = []
    por_anio = defaultdict(lambda: defaultdict(lambda: [0.0] * 24))
    for f in conta.filas:
        meses = por_anio[f["Año"]][int(f["CUENTA"])]
        m = f["FECHA"].month - 1
        meses[m * 2] += f["DEBE"]
        meses[m * 2 + 1] += f["HABER"]
    saldo_inicial = defaultdict(float)
    for anio in sorted(por_anio):
        for cuenta in sorted(por_anio[anio]):
            meses = [r2(x) for x in por_anio[anio][cuenta]]
            ini = saldo_inicial[cuenta] if str(cuenta)[0] in "12345" else 0.0
            nif = f"B{rng_nif(cuenta, e['codigo'])}" if str(cuenta)[:2] in ("40", "41", "43") else ""
            fila = {
                "CODIGO": cuenta, "TITULO": conta.titulos.get(cuenta, CUENTAS.get(int(str(cuenta)[:3] + "0" * 9), "")),
                "NOTAS": "", "DEBEINI": r2(max(ini, 0)), "HABERINI": r2(max(-ini, 0)),
                "DEBEACU": r2(sum(meses[0::2])), "HABERACU": r2(sum(meses[1::2])),
                "TIPO": "N", "NIF": nif, "SEXISTEN": 0.0, "DESCRIP": "", "DESCRIPCION_SII": "",
                "Año": anio, "Codigo_empresa": e["codigo"],
            }
            for i, mes in enumerate(MESES_MAY):
                fila["D" + mes], fila["H" + mes] = meses[i * 2], meses[i * 2 + 1]
            filas.append(fila)
        # El saldo inicial del año siguiente sale de los movimientos sin contar el asiento de cierre
        for f in conta.filas:
            if f["Año"] == anio and f["TIPO"] != "CIER":
                saldo_inicial[int(f["CUENTA"])] += f["DEBE"] - f["HABER"]
    return filas


def rng_nif(cuenta, codigo):
    return f"{(cuenta * 7919 + codigo * 104729) % 10**8:08d}"


def generar(hasta):
    rng = random.Random(SEMILLA)
    dia, may, cla, empresa, sujetos = [], [], [], [], []
    for n, e in enumerate(EMPRESAS, start=1):
        conta = generar_empresa(e, hasta, rng)
        dia += conta.filas
        may += construir_may(conta, e)
        for anio in range(ANIO_INICIO, hasta.year + 1):
            for clave, descrip in e["centros"].items():
                cla.append({"CLAVE": clave, "DESCRIP": descrip, "BAJA": 0.0, "Año": anio, "Codigo_empresa": e["codigo"]})
        alta = date(2010 + n, n, 1)
        empresa.append({**{c: None for c in COLUMNAS_EMPRESA},
                        "CC": e["codigo"], "DOMICILIO": f"CALLE FICTICIA {n * 7}", "CP": f"{n:02d}001",
                        "POBLACION": e["poblacion"], "PROVINCIA": e["poblacion"], "TELEF1": f"900000{n:03d}",
                        "FALTA": alta, "TIPO": "S", "MONEDA": "EUR", "IDVIA": 1})
        sujetos.append({**{c: None for c in COLUMNAS_SUJETOS},
                        "CODIGO": 9000 + n, "NIF": e["nif"], "NOMBRE": e["nombre"], "NOMBCOM": e["nombre"],
                        "DOMICILIO": f"CALLE FICTICIA {n * 7}", "CP": f"{n:02d}001", "POBLACION": e["poblacion"],
                        "PROVINCIA": e["poblacion"], "TELEF1": f"900000{n:03d}", "CODEMP": str(e["codigo"]),
                        "TIPONIF": "1", "ID": 9000 + n, "IDVIA": 1})
    return {"DIA_2026": (dia, COLUMNAS_DIA), "MAY_2026": (may, COLUMNAS_MAY), "CLA_2026": (cla, COLUMNAS_CLA),
            "EMPRESA": (empresa, list(COLUMNAS_EMPRESA)), "SUJETOS": (sujetos, list(COLUMNAS_SUJETOS))}


def guardar_csv(tablas):
    CARPETA_CSV.mkdir(exist_ok=True)
    for nombre, (filas, columnas) in tablas.items():
        with open(CARPETA_CSV / f"{nombre}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=columnas, delimiter=";")
            w.writeheader()
            w.writerows(filas)
        print(f"  {nombre}: {len(filas)} filas -> csv/{nombre}.csv")


def tipo_sql(tabla, columna):
    if tabla == "EMPRESA":
        return COLUMNAS_EMPRESA[columna] or "NVARCHAR(255)"
    if tabla == "SUJETOS":
        return COLUMNAS_SUJETOS[columna] or "NVARCHAR(255)"
    return TIPOS_SQL[tabla].get(columna, "NVARCHAR(255)")


def cargar_sql(tablas, servidor, base):
    import pyodbc

    cadena = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={servidor};Trusted_Connection=yes;TrustServerCertificate=yes;"
    con = pyodbc.connect(cadena + "DATABASE=master;", autocommit=True)
    con.execute(f"IF DB_ID('{base}') IS NULL CREATE DATABASE [{base}]")
    con.close()

    con = pyodbc.connect(cadena + f"DATABASE={base};")
    cur = con.cursor()
    cur.fast_executemany = True
    for nombre, (filas, columnas) in tablas.items():
        ddl = ", ".join(f"[{c}] {tipo_sql(nombre, c)} NULL" for c in columnas)
        cur.execute(f"DROP TABLE IF EXISTS dbo.[{nombre}]")
        cur.execute(f"CREATE TABLE dbo.[{nombre}] ({ddl})")
        sql = f"INSERT INTO dbo.[{nombre}] ({', '.join(f'[{c}]' for c in columnas)}) VALUES ({', '.join('?' * len(columnas))})"
        datos = [tuple(f.get(c) for c in columnas) for f in filas]
        for i in range(0, len(datos), 5000):
            cur.executemany(sql, datos[i:i + 5000])
        con.commit()
        print(f"  {servidor}/{base}.dbo.{nombre}: {len(datos)} filas")
    con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Genera datos contables ficticios para el dashboard")
    p.add_argument("--hasta", default=str(date.today() - timedelta(days=1)), help="Fecha de corte AAAA-MM-DD (por defecto, ayer)")
    p.add_argument("--cargar", action="store_true", help="Cargar las tablas en SQL Server")
    p.add_argument("--servidor", default="localhost", help="Instancia de SQL Server (por defecto localhost)")
    p.add_argument("--base", default="BBDD_PowerBI", help="Base de datos de destino (por defecto BBDD_PowerBI)")
    args = p.parse_args()

    corte = date.fromisoformat(args.hasta)
    print(f"Generando datos ficticios de {ANIO_INICIO} a {corte}...")
    tablas = generar(corte)
    guardar_csv(tablas)
    if args.cargar:
        print("Cargando en SQL Server...")
        cargar_sql(tablas, args.servidor, args.base)
    print("Listo.")
