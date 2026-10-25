# Descarga automatizada de información de acciones

Script en Python (`acciones/descargar_acciones.py`) que descarga datos de cualquier acción
listada en Yahoo Finance (EE. UU., BMV con sufijo `.MX`, Europa, etc.) usando
[`yfinance`](https://github.com/ranaroussi/yfinance).

## Qué descarga

| Tabla           | Contenido                                                                 |
|-----------------|---------------------------------------------------------------------------|
| `precios`       | Histórico OHLC, Adj Close y Volumen por ticker (formato largo)             |
| `resumen`       | Último precio, rendimiento total, volatilidad anualizada, máx. drawdown    |
| `fundamentales` | Sector, industria, market cap, P/E, P/B, EPS, dividend yield, beta, etc.  |
| `dividendos`    | Historial de dividendos pagados                                           |
| `splits`        | Historial de splits                                                       |

Se guardan en `datos/` como CSV (uno por tabla) y/o un Excel con una hoja por tabla.

## Instalación

```bash
pip install -r requirements.txt
```

## Uso

```bash
# Tickers sueltos
python acciones/descargar_acciones.py --tickers AAPL MSFT NVDA WALMEX.MX

# Desde un archivo (un ticker por línea)
python acciones/descargar_acciones.py --archivo acciones/tickers_ejemplo.txt --periodo 5y

# Todas las acciones de un índice (sp500, nasdaq100, dowjones)
python acciones/descargar_acciones.py --indice sp500 --inicio 2024-01-01 --formato excel

# Datos intradía (Yahoo limita 1m a los últimos 7 días)
python acciones/descargar_acciones.py --tickers TSLA --periodo 5d --intervalo 5m --sin-info --sin-dividendos
```

Opciones principales:

- `--periodo` `1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max` (default `1y`) o `--inicio/--fin YYYY-MM-DD`
- `--intervalo` `1m,5m,15m,1h,1d,1wk,1mo` (default `1d`)
- `--formato` `csv | excel | ambos` (default `ambos`), `--salida` carpeta destino
- `--sin-info`, `--sin-dividendos` para descargas más rápidas (útil con índices grandes)

## Automatización

**Opción 1 – el propio script** (se queda corriendo y descarga cada día a la hora indicada):

```bash
python acciones/descargar_acciones.py --archivo acciones/tickers_ejemplo.txt --programar 18:30
```

**Opción 2 – cron (Linux/macOS)**, de lunes a viernes a las 18:30:

```cron
30 18 * * 1-5 cd /ruta/al/repo && python acciones/descargar_acciones.py --archivo acciones/tickers_ejemplo.txt >> descarga.log 2>&1
```

**Opción 3 – Programador de tareas de Windows**: crear una tarea básica que ejecute
`python` con los argumentos `acciones\descargar_acciones.py --archivo acciones\tickers_ejemplo.txt`
y como carpeta de inicio la del repositorio.

## Notas

- Los tickers que no existan o no devuelvan datos se reportan como advertencia y no detienen la descarga.
- Yahoo Finance es una fuente gratuita no oficial: puede limitar peticiones si se descargan
  miles de tickers seguidos; el script descarga precios en lotes de 50 y hace una pausa
  breve entre consultas de fundamentales.
