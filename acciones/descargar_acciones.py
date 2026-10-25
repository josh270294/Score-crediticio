#!/usr/bin/env python3
"""Automatización para descargar información de acciones desde Yahoo Finance.

Descarga, para una lista de tickers:
  * Precios históricos (Open, High, Low, Close, Adj Close, Volume)
  * Información fundamental (sector, capitalización, P/E, dividend yield, etc.)
  * Dividendos y splits

y los guarda en CSV y/o en un archivo Excel con una hoja por tipo de dato.

Ejemplos:
  python acciones/descargar_acciones.py --tickers AAPL MSFT NVDA
  python acciones/descargar_acciones.py --archivo acciones/tickers_ejemplo.txt --periodo 5y
  python acciones/descargar_acciones.py --indice sp500 --inicio 2024-01-01 --formato excel
  python acciones/descargar_acciones.py --tickers AAPL --programar 18:30   # diario
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

log = logging.getLogger("acciones")

# Campos de Ticker.info que se exportan en la tabla de fundamentales.
CAMPOS_INFO = [
    "shortName", "longName", "exchange", "currency", "country", "sector", "industry",
    "marketCap", "enterpriseValue", "currentPrice", "previousClose",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyDayAverage", "twoHundredDayAverage",
    "trailingPE", "forwardPE", "priceToBook", "trailingEps", "forwardEps",
    "dividendYield", "payoutRatio", "beta", "profitMargins", "returnOnEquity",
    "debtToEquity", "totalRevenue", "ebitda", "freeCashflow",
    "sharesOutstanding", "averageVolume", "recommendationKey", "targetMeanPrice",
]

INDICES = {
    "sp500": ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "Symbol"),
    "nasdaq100": ("https://en.wikipedia.org/wiki/Nasdaq-100", "Ticker"),
    "dowjones": ("https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average", "Symbol"),
}


# --------------------------------------------------------------------------- #
# Obtención de tickers
# --------------------------------------------------------------------------- #
def leer_tickers_archivo(ruta: Path) -> list[str]:
    tickers = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if linea:
            tickers.extend(t.strip().upper() for t in linea.replace(",", " ").split())
    return tickers


def tickers_de_indice(nombre: str) -> list[str]:
    """Obtiene los componentes de un índice desde Wikipedia."""
    url, columna = INDICES[nombre]
    html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    for tabla in pd.read_html(StringIO(html)):
        if columna in tabla.columns:
            # Yahoo usa "-" en lugar de "." (p. ej. BRK.B -> BRK-B)
            return [str(t).strip().replace(".", "-") for t in tabla[columna].dropna()]
    raise RuntimeError(f"No se encontró la columna '{columna}' en {url}")


def deduplicar(tickers: list[str]) -> list[str]:
    return list(dict.fromkeys(t.upper() for t in tickers if t))


# --------------------------------------------------------------------------- #
# Descarga
# --------------------------------------------------------------------------- #
def descargar_precios(tickers: list[str], periodo: str | None, inicio: str | None,
                      fin: str | None, intervalo: str, lote: int = 50) -> pd.DataFrame:
    """Devuelve precios históricos en formato largo: Date, Ticker, Open, High, ..."""
    partes = []
    for i in range(0, len(tickers), lote):
        grupo = tickers[i:i + lote]
        log.info("Descargando precios %d-%d de %d", i + 1, i + len(grupo), len(tickers))
        datos = yf.download(
            grupo,
            period=None if inicio else periodo,
            start=inicio,
            end=fin,
            interval=intervalo,
            group_by="ticker",
            auto_adjust=False,
            actions=False,
            threads=True,
            progress=False,
        )
        if datos.empty:
            continue
        if not isinstance(datos.columns, pd.MultiIndex):
            datos.columns = pd.MultiIndex.from_product([grupo, datos.columns])
        largo = datos.stack(level=0, future_stack=True).rename_axis(["Date", "Ticker"])
        partes.append(largo.dropna(how="all").reset_index())

    if not partes:
        return pd.DataFrame()
    precios = pd.concat(partes, ignore_index=True)
    columnas = ["Date", "Ticker", "Open", "High", "Low", "Close", "Adj Close", "Volume"]
    precios = precios[[c for c in columnas if c in precios.columns]]
    return precios.sort_values(["Ticker", "Date"]).reset_index(drop=True)


def descargar_info(tickers: list[str], pausa: float = 0.2) -> pd.DataFrame:
    filas = []
    for n, t in enumerate(tickers, 1):
        try:
            info = yf.Ticker(t).info or {}
            filas.append({"Ticker": t, **{c: info.get(c) for c in CAMPOS_INFO}})
            log.info("[%d/%d] Info %s ok", n, len(tickers), t)
        except Exception as e:  # noqa: BLE001 - un ticker fallido no detiene el resto
            log.warning("[%d/%d] Info %s falló: %s", n, len(tickers), t, e)
            filas.append({"Ticker": t})
        time.sleep(pausa)
    return pd.DataFrame(filas, columns=["Ticker", *CAMPOS_INFO])


def descargar_acciones_corporativas(tickers: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    dividendos, splits = [], []
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            d, s = tk.dividends, tk.splits
            if not d.empty:
                dividendos.append(d.rename("Dividend").rename_axis("Date").reset_index().assign(Ticker=t))
            if not s.empty:
                splits.append(s.rename("Split").rename_axis("Date").reset_index().assign(Ticker=t))
        except Exception as e:  # noqa: BLE001
            log.warning("Dividendos/splits %s falló: %s", t, e)
    unir = lambda partes, cols: (pd.concat(partes, ignore_index=True)[cols]
                                 if partes else pd.DataFrame(columns=cols))
    return unir(dividendos, ["Date", "Ticker", "Dividend"]), unir(splits, ["Date", "Ticker", "Split"])


def resumen(precios: pd.DataFrame) -> pd.DataFrame:
    """Métricas rápidas por ticker a partir de los precios descargados."""
    if precios.empty:
        return pd.DataFrame()
    filas = []
    for t, g in precios.groupby("Ticker"):
        c = g["Adj Close"] if "Adj Close" in g else g["Close"]
        c = c.dropna()
        if c.empty:
            continue
        rend = c.pct_change().dropna()
        filas.append({
            "Ticker": t,
            "Desde": g["Date"].min(),
            "Hasta": g["Date"].max(),
            "Ultimo": c.iloc[-1],
            "Rendimiento_total_%": (c.iloc[-1] / c.iloc[0] - 1) * 100,
            "Volatilidad_anual_%": rend.std() * (252 ** 0.5) * 100 if len(rend) > 1 else None,
            "Max_drawdown_%": ((c / c.cummax()) - 1).min() * 100,
            "Maximo": c.max(),
            "Minimo": c.min(),
        })
    return pd.DataFrame(filas)


# --------------------------------------------------------------------------- #
# Exportación
# --------------------------------------------------------------------------- #
def _sin_zona_horaria(df: pd.DataFrame) -> pd.DataFrame:
    """Excel no admite fechas con zona horaria."""
    df = df.copy()
    for col in df.columns:
        if isinstance(df[col].dtype, pd.DatetimeTZDtype):
            df[col] = df[col].dt.tz_localize(None)
    return df


def guardar(tablas: dict[str, pd.DataFrame], salida: Path, formato: str) -> list[Path]:
    salida.mkdir(parents=True, exist_ok=True)
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    archivos = []
    if formato in ("csv", "ambos"):
        for nombre, df in tablas.items():
            ruta = salida / f"{nombre}_{sello}.csv"
            df.to_csv(ruta, index=False)
            archivos.append(ruta)
    if formato in ("excel", "ambos"):
        ruta = salida / f"acciones_{sello}.xlsx"
        with pd.ExcelWriter(ruta, engine="openpyxl") as xw:
            for nombre, df in tablas.items():
                _sin_zona_horaria(df).to_excel(xw, sheet_name=nombre[:31], index=False)
        archivos.append(ruta)
    return archivos


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #
def ejecutar(args: argparse.Namespace) -> int:
    tickers = list(args.tickers or [])
    if args.archivo:
        tickers += leer_tickers_archivo(Path(args.archivo))
    if args.indice:
        log.info("Obteniendo componentes del índice %s", args.indice)
        tickers += tickers_de_indice(args.indice)
    tickers = deduplicar(tickers)
    if not tickers:
        log.error("No hay tickers. Usa --tickers, --archivo o --indice.")
        return 2
    log.info("Tickers a procesar (%d): %s", len(tickers), ", ".join(tickers[:20])
             + (" ..." if len(tickers) > 20 else ""))

    tablas: dict[str, pd.DataFrame] = {}
    precios = descargar_precios(tickers, args.periodo, args.inicio, args.fin, args.intervalo)
    tablas["precios"] = precios
    tablas["resumen"] = resumen(precios)
    if not args.sin_info:
        tablas["fundamentales"] = descargar_info(tickers)
    if not args.sin_dividendos:
        tablas["dividendos"], tablas["splits"] = descargar_acciones_corporativas(tickers)

    sin_datos = sorted(set(tickers) - set(precios["Ticker"]) if not precios.empty else tickers)
    if sin_datos:
        log.warning("Sin precios para: %s", ", ".join(sin_datos))

    for ruta in guardar(tablas, Path(args.salida), args.formato):
        log.info("Guardado: %s", ruta)
    return 0 if not precios.empty else 1


def programar(hora: str, args: argparse.Namespace) -> None:
    """Ejecuta la descarga todos los días a la hora indicada (HH:MM, hora local)."""
    hh, mm = map(int, hora.split(":"))
    while True:
        ahora = datetime.now()
        proxima = ahora.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if proxima <= ahora:
            proxima += timedelta(days=1)
        log.info("Próxima ejecución: %s", proxima.strftime("%Y-%m-%d %H:%M"))
        time.sleep((proxima - ahora).total_seconds())
        try:
            ejecutar(args)
        except Exception:  # noqa: BLE001 - el programador debe seguir vivo
            log.exception("La ejecución programada falló")


def parsear_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Descarga información de acciones (Yahoo Finance).")
    g = p.add_argument_group("tickers")
    g.add_argument("--tickers", nargs="+", help="Lista de tickers, p. ej. AAPL MSFT WALMEX.MX")
    g.add_argument("--archivo", help="Archivo de texto con un ticker por línea")
    g.add_argument("--indice", choices=sorted(INDICES), help="Descargar todos los componentes de un índice")
    g = p.add_argument_group("rango")
    g.add_argument("--periodo", default="1y",
                   help="1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max (ignorado si se usa --inicio)")
    g.add_argument("--inicio", help="Fecha inicial YYYY-MM-DD")
    g.add_argument("--fin", help="Fecha final YYYY-MM-DD (exclusiva)")
    g.add_argument("--intervalo", default="1d", help="1m,5m,15m,1h,1d,1wk,1mo")
    g = p.add_argument_group("salida")
    g.add_argument("--salida", default="datos", help="Carpeta de salida (default: datos)")
    g.add_argument("--formato", choices=["csv", "excel", "ambos"], default="ambos")
    g.add_argument("--sin-info", action="store_true", help="No descargar fundamentales")
    g.add_argument("--sin-dividendos", action="store_true", help="No descargar dividendos/splits")
    p.add_argument("--programar", metavar="HH:MM", help="Repetir la descarga cada día a esa hora")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parsear_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    if args.programar:
        programar(args.programar, args)
        return 0
    return ejecutar(args)


if __name__ == "__main__":
    sys.exit(main())
