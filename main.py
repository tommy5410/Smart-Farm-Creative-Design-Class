"""
접속: http://127.0.0.1:8000

"""

import math
import time
from datetime import datetime
from io import StringIO
from threading import Lock

import pandas as pd
import requests
from html import escape
from typing import Annotated
from urllib.parse import urlencode

import uvicorn
from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel


app = FastAPI(
    title="스마트팜 진단 · 외부 기상 API 통합",
    description="주소로 온습도를 전달하면 계산 결과를 HTML 또는 JSON으로 반환합니다. 모든 판정 범위는 실습용 예시입니다.",
    version="2.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],
    allow_credentials=False, allow_methods=["GET"], allow_headers=["Accept"],
)


CROPS = {
    "tomato": {"name": "토마토", "temp": (20, 28), "humidity": (60, 80), "vpd": (0.6, 1.4)},
    "strawberry": {"name": "딸기", "temp": (15, 25), "humidity": (60, 80), "vpd": (0.4, 1.2)},
    "lettuce": {"name": "상추", "temp": (15, 24), "humidity": (60, 80), "vpd": (0.4, 1.0)},
}


Temperature = Annotated[float, Query(ge=-10, le=50, allow_inf_nan=False, description="온도(℃): -10~50")]
Humidity = Annotated[float, Query(ge=0, le=100, allow_inf_nan=False, description="상대습도(%): 0~100")]


class CheckResult(BaseModel):
    item: str
    value: float
    unit: str
    minimum: float
    maximum: float
    status: str
    explanation: str


class Diagnosis(BaseModel):
    crop: str
    crop_name: str
    temperature_c: float
    relative_humidity_pct: float
    saturation_vapor_pressure_kpa: float
    actual_vapor_pressure_kpa: float
    vpd_kpa: float
    overall_status: str
    warning_count: int
    checks: list[CheckResult]
    note: str


# 2. 분석 함수
def analyze(crop: str, temp: float, humidity: float) -> Diagnosis:
    if crop not in CROPS:
        raise HTTPException(status_code=404, detail="지원하지 않는 작물입니다. tomato, strawberry, lettuce 중 하나를 사용하세요.")
    config = CROPS[crop]


    saturation = 0.6108 * math.exp(17.27 * temp / (temp + 237.3))
    actual = saturation * humidity / 100
    vpd = saturation - actual

    specifications = [
        ("온도", temp, "℃", config["temp"], "온도가 예시 범위보다 낮습니다.", "온도가 예시 범위보다 높습니다."),
        ("상대습도", humidity, "%", config["humidity"], "공기가 예시 범위보다 건조합니다.", "공기가 예시 범위보다 습합니다."),
        ("공기 VPD", vpd, "kPa", config["vpd"], "수증기압차가 작아 증산 구동력이 낮은 조건입니다.", "수증기압차가 커 수분 손실이 커질 수 있는 조건입니다."),
    ]
    checks = []
    for item, value, unit, limits, low_text, high_text in specifications:
        minimum, maximum = limits
        if value < minimum:
            status, explanation = "낮음", low_text
        elif value > maximum:
            status, explanation = "높음", high_text
        else:
            status, explanation = "범위 내", "설정한 실습용 예시 범위에 들어갑니다."
        # 판정은 반올림 전 값으로 하고, 표시할 값만 반올림합니다.
        checks.append(CheckResult(
            item=item, value=round(value, 4), unit=unit,
            minimum=minimum, maximum=maximum,
            status=status, explanation=explanation,
        ))
    warning_count = sum(check.status != "범위 내" for check in checks)
    return Diagnosis(
        crop=crop, crop_name=config["name"], temperature_c=temp,
        relative_humidity_pct=humidity,
        saturation_vapor_pressure_kpa=round(saturation, 4),
        actual_vapor_pressure_kpa=round(actual, 4), vpd_kpa=round(vpd, 4),
        overall_status="예시 범위 내" if warning_count == 0 else "주의",
        warning_count=warning_count, checks=checks,
        note="작물별 범위는 임의로 설정한 실습용 예시입니다. 실제 재배 처방이 아닙니다. 공기 VPD이며 잎 온도·광량·생육 단계는 반영하지 않았습니다.",
    )


STYLE = """
*{box-sizing:border-box}body{margin:0;background:#f4f7f5;color:#173c30;font-family:'Malgun Gothic',Arial,sans-serif;line-height:1.7}
main{max-width:940px;margin:auto;padding:42px 24px}header{border-bottom:1px solid #cddbd3;padding-bottom:25px;margin-bottom:25px}
.kicker{color:#47745c;font-weight:700;letter-spacing:2px;font-size:12px}h1{font-size:clamp(26px,5vw,38px);margin:7px 0}h2{font-size:21px;margin:0 0 14px}
p{margin:8px 0}.muted{color:#53685f}.panel{background:white;border:1px solid #dce6df;border-radius:18px;padding:25px;margin:20px 0}
form{display:grid;grid-template-columns:1.2fr 1fr 1fr auto;gap:14px;align-items:end}label{display:block;font-weight:700;font-size:14px}
input,select,button{width:100%;font:inherit;border-radius:9px;padding:11px;margin-top:6px}input,select{border:1px solid #bdcec3;background:#fff;color:#173c30}
button{background:#245b41;color:white;border:0;cursor:pointer;font-weight:700}button:hover{background:#183e2d}button:disabled{opacity:.6;cursor:wait}details{margin:18px 0}summary{cursor:pointer;font-weight:700}h3{margin-top:24px}
a{color:#245b41;text-underline-offset:3px}.examples{display:flex;gap:15px;flex-wrap:wrap;font-size:14px;margin-top:18px}
.result-title{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.pill{padding:5px 13px;border-radius:30px;font-size:14px;font-weight:700}
.ok{background:#e4f3e8;color:#245b41}.warn{background:#fff0d5;color:#885800}.error{background:#fff1f0;border-color:#edc9c5;color:#81372f}
.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;white-space:nowrap}th,td{text-align:left;padding:12px;border-bottom:1px solid #e5ece7}th{font-size:13px;color:#53685f}
ul{padding-left:22px}.note{font-size:13px;border-left:3px solid #92ac9b;padding-left:14px;color:#53685f}
code{font-family:Consolas,monospace;background:#eef3ef;padding:3px 6px;border-radius:4px;overflow-wrap:anywhere}.url{display:block;white-space:normal;font-size:13px;margin:10px 0}
footer{font-size:13px;color:#60756a;margin-top:28px}.links{display:flex;gap:18px;flex-wrap:wrap;margin-top:16px}
@media(max-width:700px){form{grid-template-columns:1fr 1fr}form label:first-child{grid-column:1/-1}form button{grid-column:1/-1}.panel{padding:18px}main{padding:25px 16px}}
"""


def page(body: str) -> str:
    return f'''<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>스마트팜 진단 · 기상 API</title><style>{STYLE}</style></head>
<body><main><header><div class="kicker">FASTAPI · ASSIGNMENT 01</div>
<h1>스마트팜 진단 · 기상 API</h1><p class="muted">직접 입력한 온실 환경과 외부 관측소의 과거 기상자료를 각각 분석합니다.</p><nav class="links"><a href="/">통합 입력 화면</a><a href="/diagnose/tomato?temp=25&amp;humidity=70">온실 진단 예시</a><a href="/weather/146?year=2023">외부 API 예시</a><a href="/docs">API 문서</a></nav></header>
{body}<footer>FastAPI · GET · 외부 CSV API · pandas · 비동기 fetch · 입력 검증 · HTML/JSON/CSV<br>외부 관측자료는 온실 센서값이 아니며, 작물별 판정 범위는 실습용 예시입니다.</footer></main>{AJAX_SCRIPT}</body></html>'''


def input_form(crop: str = "tomato", temp: float = 25, humidity: float = 70) -> str:
    options = "".join(
        f'<option value="{key}" {"selected" if key == crop else ""}>{config["name"]}</option>'
        for key, config in CROPS.items()
    )
    return f'''<section class="panel"><h2>환경값 입력</h2>
<form action="/diagnose" method="get" data-ajax="diagnose" data-target="diagnosis-result">
<label>작물<select name="crop">{options}</select></label>
<label>온도 (℃)<input name="temp" type="number" min="-10" max="50" step="any" value="{temp:g}" required></label>
<label>상대습도 (%)<input name="humidity" type="number" min="0" max="100" step="any" value="{humidity:g}" required></label>
<button type="submit">환경 진단하기</button></form>
<div class="examples"><span>빠른 시연:</span>
<a href="/diagnose/tomato?temp=25&humidity=70">예시 범위 내</a>
<a href="/diagnose/tomato?temp=30&humidity=45">고온·건조</a>
<a href="/diagnose/tomato?temp=18&humidity=95">저온·다습</a></div></section>'''


def result_html(result: Diagnosis) -> str:
    rows = "".join(
        f'<tr><td>{check.item}</td><td>{check.value:g} {check.unit}</td>'
        f'<td>{check.minimum:g}~{check.maximum:g} {check.unit}</td>'
        f'<td><span class="pill {"ok" if check.status == "범위 내" else "warn"}">{check.status}</span></td></tr>'
        for check in result.checks
    )
    explanations = "".join(f"<li><strong>{c.item}:</strong> {c.explanation}</li>" for c in result.checks)
    query = urlencode({"temp": result.temperature_c, "humidity": result.relative_humidity_pct})
    html_url = f"/diagnose/{result.crop}?{query}"
    api_url = f"/api/diagnose/{result.crop}?{query}"
    return f'''<section class="panel"><div class="result-title"><h2>{result.crop_name} 환경 진단 결과</h2>
<span class="pill {"ok" if result.warning_count == 0 else "warn"}">{result.overall_status} · 범위 밖 {result.warning_count}개</span></div>
<div class="table-wrap"><table><thead><tr><th>항목</th><th>입력 / 계산값</th><th>실습용 예시 범위</th><th>판정</th></tr></thead><tbody>{rows}</tbody></table></div>
<ul>{explanations}</ul><p class="note">{result.note}</p>
<details><summary>계산 원리 보기</summary>
<p>VPD(수증기압차)는 공기가 수증기로 포화되었을 때와 현재 상태 사이의 압력 차이입니다.</p>
<p><code>es = 0.6108 × exp(17.27 × T / (T + 237.3))</code><br>
<code>ea = es × RH / 100</code><br><code>VPD = es - ea</code></p>
<p>T: 온도(℃), RH: 상대습도(%), es·ea·VPD: kPa</p>
<p>포화수증기압: {result.saturation_vapor_pressure_kpa:g} kPa / 실제수증기압: {result.actual_vapor_pressure_kpa:g} kPa</p>
<p>판정은 반올림 전 값으로 수행합니다. 표시된 값은 소수점 넷째 자리까지 반올림합니다.</p></details>
<div class="links"><a href="{escape(api_url, quote=True)}">같은 결과를 JSON으로 보기</a><a href="/docs">API 문서 보기</a></div>
<p class="muted">주소창에서 직접 입력할 수 있는 결과 주소:</p>
<code class="url">http://127.0.0.1:8000{escape(html_url)}</code></section>'''


def render_diagnosis(crop: str, temp: float, humidity: float) -> str:
    result = analyze(crop, temp, humidity)
    return page(input_form(crop, temp, humidity) + '<div id="diagnosis-result" role="status" aria-live="polite">' + result_html(result) + '</div>')


API_BASE = "https://api.taegon.kr"
CACHE_TTL = 600
CACHE_LIMIT = 16
WEATHER_CACHE = {}
CACHE_LOCK = Lock()
Year = Annotated[int, Query(ge=1900, le=datetime.now().year, description="조회 연도")]
Month = Annotated[int, Query(ge=0, le=12, description="0: 연간, 1~12: 해당 월")]
Station = Annotated[int, Path(ge=1, le=999, description="관측지점 번호. 수업자료 예시: 146")]
WEATHER_COLUMNS = ["tmax", "tavg", "tmin", "humid", "rainfall"]


def source_url(station: int, year: int) -> str:
    return f"{API_BASE}/stations/{station}/?{urlencode({'sy': year, 'ey': year, 'format': 'csv'})}"


def parse_weather(csv_text: str, year: int):
    """실제 응답의 열 이름을 검증하고 날짜/숫자/결측값을 정리합니다."""
    try:
        df = pd.read_csv(StringIO(csv_text), skipinitialspace=True)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeError, ValueError):
        raise HTTPException(502, "외부 API 응답을 CSV로 읽을 수 없습니다.")
    df.columns = df.columns.astype(str).str.strip().str.lower().str.lstrip("\ufeff")
    if df.columns.duplicated().any():
        raise HTTPException(502, "외부 CSV에 중복된 열 이름이 있습니다.")
    required = {"year", "month", "day", *WEATHER_COLUMNS}
    if not required.issubset(df.columns):
        missing = ", ".join(sorted(required - set(df.columns)))
        raise HTTPException(502, f"외부 API의 CSV 형식이 예상과 다릅니다. 없는 열: {missing}")
    if len(df) > 10000:
        raise HTTPException(502, "연도별 기상자료의 행 수가 예상보다 너무 많습니다.")
    source_rows = len(df)
    date_parts = df[["year", "month", "day"]].apply(pd.to_numeric, errors="coerce")
    # 소수 날짜나 무한대 날짜는 먼저 제거
    valid_parts = date_parts.notna().all(axis=1) & date_parts.isin([float("inf"), float("-inf")]).sum(axis=1).eq(0)
    valid_parts &= (date_parts.fillna(0) % 1 == 0).all(axis=1)
    df = df.loc[valid_parts].copy()
    df["date"] = pd.to_datetime(date_parts.loc[valid_parts], errors="coerce")
    df = df.loc[df["date"].notna() & df["date"].dt.year.eq(year)].copy()
    invalid_dates = source_rows - len(df)
    duplicate_dates = int(df["date"].duplicated().sum())
    df = df.drop_duplicates("date", keep="last").sort_values("date")
    if df.empty:
        raise HTTPException(404, "조회 연도에 유효한 기상자료가 없습니다. 146 지점의 2023년으로 먼저 시도해보세요.")
   
    for column in WEATHER_COLUMNS:
        values = pd.to_numeric(df[column], errors="coerce")
        values = values.mask(values.isin([-99, -999, -9999, float("inf"), float("-inf")]))
        if column in ("tmax", "tavg", "tmin"):
            values = values.where(values.between(-80, 60))
        elif column == "humid":
            values = values.where(values.between(0, 100))
        else:
            values = values.where(values >= 0)
        df[column] = values
    # 평균이 최저~최고 사이가 아닌 날은 세 온도 값을 계산에서 제외
    full_temp = df[["tmin", "tavg", "tmax"]].notna().all(axis=1)
    inconsistent = full_temp & ((df["tmin"] > df["tavg"]) | (df["tavg"] > df["tmax"]))
    df.loc[inconsistent, ["tmin", "tavg", "tmax"]] = float("nan")
    # 세 온도가 모두 0인 날은 의심 사례로 표시, 결측이라고 단정해 삭제
    zero_temp_days = int(df[["tmin", "tavg", "tmax"]].eq(0).all(axis=1).sum())
    es = 0.6108 * ((17.27 * df["tavg"] / (df["tavg"] + 237.3)).map(math.exp))
    df["vpd_proxy"] = es * (1 - df["humid"] / 100)
    df = df[["date", *WEATHER_COLUMNS, "vpd_proxy"]].reset_index(drop=True)
    quality = {
        "source_rows": source_rows, "valid_unique_days": len(df),
        "invalid_or_outside_year_rows": invalid_dates,
        "duplicate_date_rows": duplicate_dates,
        "inconsistent_temperature_days": int(inconsistent.sum()),
        "all_zero_temperature_days": zero_temp_days,
    }
    return df, quality


def fetch_weather(station: int, year: int):
    key = (station, year)
    with CACHE_LOCK:
        cached = WEATHER_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL:
            return cached[1].copy(), dict(cached[2]), cached[3], True
    url = source_url(station, year)
    try:
        
        response = requests.get(url, timeout=(5, 20), allow_redirects=False)
        if response.status_code == 404:
            raise HTTPException(404, "외부 API에 해당 지점 또는 연도 자료가 없습니다.")
        if not 200 <= response.status_code < 300:
            raise HTTPException(502, f"외부 기상 API 응답 오류: HTTP {response.status_code}")
        if len(response.content) > 5_000_000:
            raise HTTPException(502, "외부 API 응답 크기가 너무 큽니다.")
        csv_text = response.content.decode("utf-8-sig")
    except requests.Timeout:
        raise HTTPException(504, "기상 API 응답 시간이 초과되었습니다. 잠시 후 다시 조회하세요.")
    except requests.RequestException:
        raise HTTPException(502, "외부 기상 API에 연결하지 못했습니다. 인터넷 연결이나 외부 서버 상태를 확인하세요.")
    except UnicodeDecodeError:
        raise HTTPException(502, "외부 CSV의 문자 인코딩을 읽을 수 없습니다.")
    df, quality = parse_weather(csv_text, year)
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with CACHE_LOCK:
        if len(WEATHER_CACHE) >= CACHE_LIMIT:
            oldest = min(WEATHER_CACHE, key=lambda k: WEATHER_CACHE[k][0])
            WEATHER_CACHE.pop(oldest, None)
        WEATHER_CACHE[key] = (time.monotonic(), df.copy(), dict(quality), fetched_at)
    return df, quality, fetched_at, False


def finite_number(value, digits=3):
    return round(float(value), digits) if pd.notna(value) and math.isfinite(float(value)) else None


def summary_statistics(df):
    return {
        "days": len(df),
        "mean_temperature_c": finite_number(df["tavg"].mean()),
        "highest_temperature_c": finite_number(df["tmax"].max()),
        "lowest_temperature_c": finite_number(df["tmin"].min()),
        "mean_humidity_pct": finite_number(df["humid"].mean()),
        "total_rainfall_mm": finite_number(df["rainfall"].sum(min_count=1)),
        "mean_vpd_proxy_kpa": finite_number(df["vpd_proxy"].mean()),
        "hot_days_tmax_ge_30": int(df["tmax"].ge(30).sum()) if df["tmax"].notna().any() else None,
        "frost_days_tmin_lt_0": int(df["tmin"].lt(0).sum()) if df["tmin"].notna().any() else None,
        "rainy_days_rainfall_gt_0": int(df["rainfall"].gt(0).sum()) if df["rainfall"].notna().any() else None,
        "valid_counts": {c: int(df[c].notna().sum()) for c in WEATHER_COLUMNS + ["vpd_proxy"]},
        "missing_counts": {c: int(df[c].isna().sum()) for c in WEATHER_COLUMNS + ["vpd_proxy"]},
    }


def weather_data(station: int, year: int, month: int):
    df, quality, fetched_at, cached = fetch_weather(station, year)
    if month:
        df = df.loc[df["date"].dt.month.eq(month)].copy()
    if df.empty:
        raise HTTPException(404, "선택한 월의 기상자료가 없습니다.")
    monthly = []
    for number, group in df.groupby(df["date"].dt.month):
        monthly.append({"month": int(number), **summary_statistics(group)})
    records = []
    for _, row in df.iterrows():
        records.append({"date": row["date"].strftime("%Y-%m-%d"), **{
            c: finite_number(row[c], 4) for c in WEATHER_COLUMNS + ["vpd_proxy"]
        }})
    # 실제 응답은 연간 365/366개 날짜를 모두 포함하지 않을 수 있습니다.
    calendar_dates = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    if month:
        calendar_dates = calendar_dates[calendar_dates.month == month]
    # 올해 조회에서는 아직 오지 않은 날짜를 누락으로 세지 않습니다.
    calendar_dates = calendar_dates[calendar_dates <= pd.Timestamp.today().normalize()]
    missing_dates = calendar_dates.difference(pd.DatetimeIndex(df["date"]))
    coverage = {
        "calendar_days_elapsed": len(calendar_dates),
        "days_without_rows": len(missing_dates),
        "missing_dates": missing_dates.strftime("%Y-%m-%d").tolist(),
    }
    return {
        "station": station, "year": year, "month": month,
        "source_url": source_url(station, year), "fetched_at": fetched_at,
        "from_cache": cached, "cache_ttl_seconds": CACHE_TTL,
        "period_start": records[0]["date"], "period_end": records[-1]["date"],
        "summary": summary_statistics(df), "monthly": monthly, "daily": records,
        "source_quality": quality, "calendar_coverage": coverage,
        "note": "외부 관측소의 과거 일별 기상자료입니다. 실시간 또는 온실 내부 환경이 아닙니다. VPD는 일평균 온도·습도로 계산한 근사 지표이며 실제 일평균 VPD와 같지 않습니다. 통계는 가용자료 기준이며 누락 날짜·결측이 있으면 완전한 기간 통계가 아닐 수 있습니다.",
    }, df


def weather_form(station=146, year=2023, month=0):
    options = ''.join(f'<option value="{m}" {"selected" if month == m else ""}>{"연간 전체" if m == 0 else str(m) + "월"}</option>' for m in range(13))
    return f'''<section class="panel"><h2>외부 기상 API 조회</h2>
<p class="muted">수업자료 15쪽의 API에서 과거 CSV를 받아 분석합니다. 첫 시연은 지점 146 / 2023년을 추천합니다.</p>
<form action="/weather" method="get" data-ajax="weather" data-target="weather-result">
<label>지점 번호<input name="station" type="number" min="1" max="999" value="{station}" required></label>
<label>연도<input name="year" type="number" min="1900" max="{datetime.now().year}" value="{year}" required></label>
<label>조회 기간<select name="month">{options}</select></label><button type="submit">기상자료 가져오기</button></form>
<p class="note">10분 이내 동일 지점·연도는 메모리 캐시를 이용합니다. 외부 API가 실패하면 오류를 안내하며, 가짜 자료로 대신하지 않습니다.</p></section>'''


def show_number(value, unit=""):
    return "자료 없음" if value is None else f"{value:g}{unit}"


def weather_result_html(data):
    stats = data["summary"]
    definitions = [
        ("분석 날짜 수", "days", "일"), ("일평균기온의 평균", "mean_temperature_c", "℃"),
        ("최고기온의 최댓값", "highest_temperature_c", "℃"), ("최저기온의 최솟값", "lowest_temperature_c", "℃"),
        ("평균 상대습도", "mean_humidity_pct", "%"), ("누적 강수량", "total_rainfall_mm", " mm"),
        ("일평균 입력 VPD 근사값의 평균", "mean_vpd_proxy_kpa", " kPa"),
        ("최고기온 30℃ 이상", "hot_days_tmax_ge_30", "일"),
        ("최저기온 0℃ 미만", "frost_days_tmin_lt_0", "일"),
        ("강수량 0 mm 초과", "rainy_days_rainfall_gt_0", "일"),
    ]
    summary_rows = ''.join(f'<tr><td>{label}</td><td>{show_number(stats[key], unit)}</td></tr>' for label, key, unit in definitions)
    monthly_rows = ''.join(f'<tr><td>{r["month"]}월</td><td>{r["days"]}</td><td>{show_number(r["mean_temperature_c"])}</td><td>{show_number(r["mean_humidity_pct"])}</td><td>{show_number(r["total_rainfall_mm"])}</td><td>{show_number(r["mean_vpd_proxy_kpa"])}</td></tr>' for r in data["monthly"])
    # 최초 15개 날짜만 화면에 보이고, 나머지는 CSV/JSON으로 제공합니다.
    daily_rows = ''.join(f'<tr><td>{r["date"]}</td><td>{show_number(r["tavg"])}</td><td>{show_number(r["humid"])}</td><td>{show_number(r["rainfall"])}</td><td>{show_number(r["vpd_proxy"])}</td></tr>' for r in data["daily"][:15])
    quality = data["source_quality"]
    query = urlencode({"year": data["year"], "month": data["month"]})
    station = data["station"]
    status = "10분 캐시 사용" if data["from_cache"] else "외부 API에서 새로 수신"
    missing = ', '.join(f'{escape(key)}: {value}개' for key, value in stats["missing_counts"].items())
    source = escape(data["source_url"], quote=True)
    return f'''<section class="panel"><div class="result-title"><h2>관측지점 {station} 기상 분석</h2><span class="pill ok">{status}</span></div>
<p>{data["period_start"]} ~ {data["period_end"]} · 조회: {escape(data["fetched_at"])}</p>
<p class="note">{data["note"]}</p>
<div class="table-wrap"><table><thead><tr><th>통계 항목</th><th>값</th></tr></thead><tbody>{summary_rows}</tbody></table></div>
<h3>월별 요약</h3><div class="table-wrap"><table><thead><tr><th>월</th><th>날짜 수</th><th>평균기온(℃)</th><th>평균습도(%)</th><th>강수합(mm)</th><th>VPD 근사(kPa)</th></tr></thead><tbody>{monthly_rows}</tbody></table></div>
<details><summary>일별 자료 미리보기 · 최초 15개 날짜</summary><div class="table-wrap"><table><thead><tr><th>날짜</th><th>평균기온(℃)</th><th>습도(%)</th><th>강수(mm)</th><th>VPD 근사(kPa)</th></tr></thead><tbody>{daily_rows}</tbody></table></div></details>
<details><summary>데이터 품질 및 결측값 확인</summary>
<p>선택 기간의 경과한 달력 날짜: {data["calendar_coverage"]["calendar_days_elapsed"]}일 / 행 자체가 없는 날짜: {data["calendar_coverage"]["days_without_rows"]}일</p>
<p>행이 없는 날짜 미리보기(최대 10개): {', '.join(data["calendar_coverage"]["missing_dates"][:10]) or '없음'}</p>
<p>선택 기간의 항목별 결측 수: {missing}</p>
<p>연도 원본: {quality["source_rows"]}행 / 유효한 중복 없는 날짜: {quality["valid_unique_days"]}일 / 날짜 오류·다른 연도: {quality["invalid_or_outside_year_rows"]}행 / 중복 날짜: {quality["duplicate_date_rows"]}행</p>
<p>온도 순서가 맞지 않는 날짜: {quality["inconsistent_temperature_days"]}일(세 온도는 결측 처리)</p>
<p>최고·평균·최저기온이 모두 0인 날짜: {quality["all_zero_temperature_days"]}일(의심 사례로 표시하지만 그대로 유지)</p>
<p>항목마다 유효 자료 수가 다를 수 있습니다. 결측이 있으면 강수합은 해당 기간의 완전한 총량이 아닐 수 있습니다. 날짜 사이 자료가 없는 날을 자동 보간하지 않습니다.</p></details>
<div class="links"><a href="/api/weather/{station}?{escape(query, quote=True)}">전체 JSON 보기</a><a href="/download/weather/{station}?{escape(query, quote=True)}">분석용 CSV 다운로드</a><a href="{source}" target="_blank" rel="noopener">외부 API 원본 CSV</a></div>
<p class="muted">주소창으로 직접 조회:</p><code class="url">http://127.0.0.1:8000/weather/{station}?{escape(query)}</code></section>'''



AJAX_SCRIPT = r'''<script>
document.querySelectorAll('form[data-ajax]').forEach(form => {
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const target = document.getElementById(form.dataset.target);
    const button = form.querySelector('button[type="submit"]');
    const previousLabel = button.textContent;
    const params = new URLSearchParams(new FormData(form));
    let fragment, pagePath;
    if (form.dataset.ajax === 'weather') {
      const station = params.get('station');
      params.delete('station');
      fragment = '/fragment/weather/' + encodeURIComponent(station);
      pagePath = '/weather/' + encodeURIComponent(station);
    } else {
      fragment = '/fragment/diagnose';
      pagePath = '/diagnose';
    }
    button.disabled = true;
    button.textContent = '조회 중…';
    target.setAttribute('aria-busy', 'true');
    target.innerHTML = '<section class="panel"><p>서버에서 결과를 받아오는 중입니다…</p></section>';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 35000);
    try {
      const response = await fetch(fragment + '?' + params.toString(), {
        method: 'GET', signal: controller.signal,
        headers: {'Accept': 'text/html'}
      });
      const html = await response.text();
      if (!(response.headers.get('content-type') || '').includes('text/html')) {
        throw new Error('unexpected response');
      }
      target.innerHTML = html;
      if (response.ok) {
        // 완료된 결과 주소를 주소창에 표시합니다. 직접 열어도 같은 결과를 얻습니다.
        history.replaceState(null, '', pagePath + '?' + params.toString());
      }
    } catch (error) {
      target.innerHTML = '<section class="panel error"><h2>조회하지 못했습니다</h2><p>서버가 실행 중인지와 인터넷 연결을 확인한 후 다시 시도하세요. 응답 시간이 초과되었을 수도 있습니다.</p></section>';
    } finally {
      clearTimeout(timer);
      target.removeAttribute('aria-busy');
      button.disabled = false;
      button.textContent = previousLabel;
    }
  });
});
</script>'''



@app.get("/", response_class=HTMLResponse, summary="통합 입력 화면")
def home():
    return page(input_form() + '<div id="diagnosis-result" role="status" aria-live="polite"></div>'
                + weather_form() + '<div id="weather-result" role="status" aria-live="polite"></div>')


@app.get("/diagnose", response_class=HTMLResponse, summary="온실 GET 폼 결과")
def diagnose_form(temp: Temperature = 25, humidity: Humidity = 70, crop: str = "tomato"):
    return render_diagnosis(crop, temp, humidity)


@app.get("/diagnose/{crop}", response_class=HTMLResponse, summary="주소창 입력 → 온실 HTML")
def diagnose_page(crop: str, temp: Temperature = 25, humidity: Humidity = 70):
    return render_diagnosis(crop, temp, humidity)


@app.get("/fragment/diagnose", response_class=HTMLResponse, summary="온실 결과 부분만 반환")
def diagnose_fragment(temp: Temperature = 25, humidity: Humidity = 70, crop: str = "tomato"):
    return result_html(analyze(crop, temp, humidity))


@app.get("/api/diagnose/{crop}", response_model=Diagnosis, summary="온실 JSON API")
def diagnose_api(crop: str, temp: Temperature = 25, humidity: Humidity = 70):
    return analyze(crop, temp, humidity)


@app.get("/weather", response_class=HTMLResponse, summary="기상 GET 폼 결과")
def weather_form_result(station: Annotated[int, Query(ge=1, le=999)] = 146, year: Year = 2023, month: Month = 0):
    data, _ = weather_data(station, year, month)
    return page(weather_form(station, year, month) + '<div id="weather-result" role="status" aria-live="polite">' + weather_result_html(data) + '</div>')


@app.get("/weather/{station}", response_class=HTMLResponse, summary="주소창 → 외부 기상 API → HTML")
def weather_page(station: Station, year: Year = 2023, month: Month = 0):
    return weather_form_result(station, year, month)


@app.get("/fragment/weather/{station}", response_class=HTMLResponse, summary="외부 기상 API 결과 부분만 반환")
def weather_fragment(station: Station, year: Year = 2023, month: Month = 0):
    data, _ = weather_data(station, year, month)
    return weather_result_html(data)


@app.get("/api/weather/{station}", summary="외부 기상자료 분석 JSON")
def weather_api(station: Station, year: Year = 2023, month: Month = 0):
    data, _ = weather_data(station, year, month)
    return data


@app.get("/download/weather/{station}", summary="정리한 기상자료 CSV 다운로드")
def weather_csv(station: Station, year: Year = 2023, month: Month = 0):
    _, df = weather_data(station, year, month)
    export = df.copy()
    export["date"] = export["date"].dt.strftime("%Y-%m-%d")
    content = export.to_csv(index=False, float_format="%.4f").encode("utf-8-sig")
    return Response(content=content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="weather_{station}_{year}_{month}.csv"'})


def error_response(request: Request, status_code: int, messages: list[str]):
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=status_code, content={"detail": messages})
    items = ''.join(f'<li>{escape(message)}</li>' for message in messages)
    body = f'''<section class="panel error"><h2>요청을 처리하지 못했습니다</h2><ul>{items}</ul>
<p>온도 -10~50℃ / 습도 0~100% / 지점 1~999 / 월 0~12 범위를 확인하세요.</p>
<p>작물: tomato, strawberry, lettuce. 기상자료 첫 조회: 지점 146 / 2023년.</p>
<a href="/">통합 입력 화면으로 돌아가기</a></section>'''
    return HTMLResponse(status_code=status_code, content=body if request.url.path.startswith('/fragment/') else page(body))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    labels = {"temp": "온도", "humidity": "상대습도", "crop": "작물", "station": "지점", "year": "연도", "month": "월"}
    messages = [f'{labels.get(str(e["loc"][-1]), str(e["loc"][-1]))} 입력 오류: {e["msg"]}' for e in exc.errors()]
    return error_response(request, 422, messages)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return error_response(request, exc.status_code, [str(exc.detail)])



if __name__ == "__main__":
    print("\n통합 화면: http://127.0.0.1:8000")
    print("외부 API 시연: http://127.0.0.1:8000/weather/146?year=2023")
    print("API 문서: http://127.0.0.1:8000/docs")
    print("종료: Ctrl+C\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)
