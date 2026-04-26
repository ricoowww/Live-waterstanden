import requests
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
STATION_MAP = {
    'BASEL': 'Basel',
    'MAXAU': 'Maxau',
    'OESTRICH': 'Oestrich',
    'KAUB': 'Kaub',
    'KOBLENZ': 'Koblenz',
    'KOELN': 'Keulen',
    'DUESSELDORF': 'Dusseldorf',
    'DUISBURG': 'Duisburg',
    'WESEL': 'Wesel',
}

def normalize(s):
    return (s.upper()
        .replace('Ö','OE').replace('Ü','UE').replace('Ä','AE')
        .replace('\xd6','OE').replace('\xdc','UE').replace('\xc4','AE')
    )
DASHBOARD_STATIONS = ['Basel', 'Maxau', 'Oestrich', 'Kaub', 'Koblenz', 'Keulen', 'Dusseldorf', 'Duisburg', 'Wesel', 'Nijmegen']
FORECAST_STATIONS = {
    'Oestrich': 'OESTRICH',
    'Kaub': 'KAUB',
    'Keulen': 'K%C3%96LN',
    'Duisburg': 'DUISBURG-RUHRORT',
}


def clean(text):
    text = text.replace('\xa0', '').replace('\n', ' ').strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def parse_val(s):
    s = str(s).strip()
    if s in ('--', '(--)','', 'None'):
        return None
    try:
        return int(float(s.replace(',', '.')))
    except:
        return None


def fetch_rhine_levels():
    url = 'https://www.elwis.de/DE/dynamisch/Wasserstaende/Pegelliste:ws:RHEIN'
    r = requests.get(url, headers=HEADERS, timeout=20)
    soup = BeautifulSoup(r.text, 'html.parser')
    table = soup.find('table')
    if not table:
        return {}

    levels = {}
    rows = table.find_all('tr')
    current_station = None

    for row in rows:
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue
        texts = [c.get_text(' ', strip=True) for c in cells]

        # First cell may contain station name
        first = clean(texts[0])
        first_norm = normalize(first)
        # Station rows have the name embedded in first long cell
        station_name = None
        for key in STATION_MAP:
            if key in first_norm:
                station_name = STATION_MAP[key]
                break

        if station_name:
            current_station = station_name
            if current_station not in levels:
                levels[current_station] = {}

        if current_station and len(texts) >= 3:
            # Time is usually second cell
            time_txt = clean(texts[1]) if len(texts) > 1 else ''
            # Match rows with time like 05:00:00 or 05:00
            m = re.match(r'(\d{2}):(\d{2})', time_txt)
            if not m and len(texts) > 0:
                m = re.match(r'(\d{2}):(\d{2})', first)
            if m:
                hour = f"{m.group(1)}:00"
                # Last cell is usually today's value
                val = parse_val(texts[-1])
                if val is None and len(texts) > 2:
                    val = parse_val(texts[-2])
                if hour in ['05:00', '13:00', '21:00']:
                    levels[current_station][hour] = val

    return levels


def fetch_forecast(station_key, station_name):
    url = f'https://www.elwis.de/DE/dynamisch/Wasserstaende/Pegelvorhersage:{station_key}'
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table')
        if not table:
            return None

        rows = table.find_all('tr')
        # Find date headers
        header_row = None
        for row in rows:
            cells = row.find_all(['td', 'th'])
            if cells:
                txt = cells[0].get_text(strip=True)
                if 'Heute' in txt or 'Pegel' in txt or len(cells) > 4:
                    header_row = row
                    break

        hourly = []
        dates = []

        for row in rows:
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue
            texts = [c.get_text(strip=True) for c in cells]

            # Collect date headers
            for t in texts:
                m = re.search(r'(\d{2}\.\d{2}\.\d{4})', t)
                if m and m.group(1) not in dates:
                    dates.append(m.group(1))

            # Data rows: first element is time
            time_match = re.match(r'(\d{2}:\d{2})', texts[0])
            if time_match:
                entry = {'uur': time_match.group(1)[:5]}
                vals = [parse_val(t) for t in texts[1:] if t not in ('',)]
                for i, v in enumerate(vals[:len(dates)]):
                    d = dates[i] if i < len(dates) else f'dag{i+1}'
                    entry[d] = v
                hourly.append(entry)

        return {'station': station_name, 'dates': dates, 'hourly': hourly}
    except Exception as e:
        print(f'Forecast error {station_name}: {e}')
        return None


def fetch_nijmegen():
    url = 'https://wasserkarte.net/gids/waterstand.php?plaats=Nijmegen-haven'
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, 'html.parser')

        # Current level
        current = None
        m = re.search(r'(\d{3,4})\s*cm', r.text)
        if m:
            current = int(m.group(1))

        # Look for tables with forecast
        tables = soup.find_all('table')
        forecast = {}
        for t in tables:
            rows = t.find_all('tr')
            headers = []
            for row in rows:
                cells = row.find_all(['td', 'th'])
                texts = [c.get_text(strip=True) for c in cells]
                if not headers and any(re.search(r'\d{2}:\d{2}', t) for t in texts):
                    continue
                if 'Vandaag' in ' '.join(texts) or 'Morgen' in ' '.join(texts):
                    headers = texts
                elif headers and len(texts) >= 2:
                    time_m = re.match(r'(\d{2}:\d{2})', texts[0])
                    if time_m:
                        entry = {'uur': time_m.group(1)}
                        for i, h in enumerate(headers[1:], 1):
                            if i < len(texts):
                                entry[h] = parse_val(texts[i])
                        forecast[time_m.group(1)] = entry

        # Simpler: extract digits from page sections
        vandaag_vals = []
        morgen_vals = []

        # Try to find structured forecast data
        pre = soup.find_all(['script', 'pre'])
        for p in pre:
            txt = p.get_text()
            if 'vandaag' in txt.lower() or 'morgen' in txt.lower():
                nums = re.findall(r'\b(\d{3,4})\b', txt)
                if nums:
                    vandaag_vals = [int(n) for n in nums[:12]]
                    morgen_vals = [int(n) for n in nums[12:24]]

        return {
            'current': current,
            'forecast_raw': forecast,
        }
    except Exception as e:
        print(f'Nijmegen error: {e}')
        return {'current': None}


def fetch_maxau_api():
    url = 'https://www.hochwasser.rlp.de/api/v1/measurement-site/23700200'
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        data = r.json()
        w_data = data.get('W', {})
        measurements = w_data.get('measurements', [])
        hourly = []
        for m in measurements[-72:]:
            ts = m.get('x', '')
            val = m.get('y')
            if ts and val is not None:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                hourly.append({'t': dt.strftime('%d-%m %H:%M'), 'v': val})
        return hourly
    except Exception as e:
        print(f'Maxau API error: {e}')
        return []


def run():
    print('Fetching Rhine levels...')
    levels = fetch_rhine_levels()
    print('Stations found:', list(levels.keys()))

    print('Fetching forecasts...')
    forecasts = {}
    for name, key in FORECAST_STATIONS.items():
        print(f'  {name}...')
        forecasts[name] = fetch_forecast(key, name)

    print('Fetching Nijmegen...')
    nijmegen = fetch_nijmegen()

    print('Fetching Maxau API...')
    maxau_hourly = fetch_maxau_api()

    # Build dashboard rows
    dashboard = []
    for station in DASHBOARD_STATIONS:
        lvl = levels.get(station, {})
        row = {
            'gebied': station,
            'pegel_05': lvl.get('05:00'),
            'pegel_13': lvl.get('13:00'),
            'pegel_21': lvl.get('21:00'),
        }
        if station == 'Nijmegen' and nijmegen.get('current'):
            row['pegel_nu'] = nijmegen['current']
        dashboard.append(row)

    output = {
        'updated': datetime.utcnow().isoformat() + 'Z',
        'dashboard': dashboard,
        'forecasts': forecasts,
        'nijmegen': nijmegen,
        'maxau_hourly': maxau_hourly[-48:],
    }

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print('Saved data.json')
    return output


if __name__ == '__main__':
    run()
