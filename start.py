import os
import csv
import time
from serpapi import GoogleSearch
from datetime import datetime, timedelta

# --- KONFIGURATION ---
API_KEY = "3df690d1f9320565f59357d3a1c512f3a0bb3a080bcf3f298bfe63e96af22f94"
DESTINATION = "HND"    # Tokio Haneda
CURRENCY = "EUR"

# Startflughäfen
ORIGINS = ["FRA", "MUC"]

# Reiseklassen: (Anzeigename, API-Code)
# 1 = Economy, 3 = Business
CLASSES = [("Economy", "1"), ("Business", "3")]

# Airlines Filter (Lowercase)
TARGET_AIRLINES = [
    "lufthansa", "all nippon", "ana",
    "japan airlines", "jal", "jl", "JL",
    "finnair", "emirates"
]

CSV_FILE = "flugpreise_2027_complete.csv"

def get_airline_display_name(raw_name):
    """Wandelt API-Namen in schöne Kurznamen um."""
    r = raw_name.lower()
    if "all nippon" in r or "ana" in r: return "ANA"
    if "japan airlines" in r or "jal" in r or "jl" in r: return "JAL"
    if "lufthansa" in r: return "Lufthansa"
    if "finnair" in r: return "Finnair"
    if "emirates" in r: return "Emirates"
    return raw_name # Fallback

def search_flights(origin, date_out, date_ret, cabin_name, cabin_code):
    """
    Sucht Round-Trip Flüge und gibt den günstigsten pro Airline zurück.
    """
    print(f"  > Suche: {origin}->{DESTINATION} | {cabin_name} | {date_out} bis {date_ret}")

    params = {
        "api_key": API_KEY,
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": DESTINATION,
        "outbound_date": date_out,
        "return_date": date_ret,
        "currency": CURRENCY,
        "gl": "de",
        "hl": "de",
        "travel_class": cabin_code,
        "stops": "1",           # Max 1 Stopp
        "type": "1",            # Round Trip
    }

    results_per_airline = {}

    try:
        search = GoogleSearch(params)
        results = search.get_dict()

        if "error" in results:
            print(f"    ! API Fehler: {results['error']}")
            return []

        all_flights = results.get("best_flights", []) + results.get("other_flights", [])

        if not all_flights:
            return []

        for flight in all_flights:
            flights_list = flight.get('flights', [])
            if not flights_list: continue

            # --- Airline Bestimmung ---
            # Wir nehmen die Airline des ersten Segments (Hinflug Start)
            first_leg = flights_list[0]
            airline_raw = first_leg.get('airline', '')

            # Prüfen ob Airline gewünscht ist
            is_target = False
            for t in TARGET_AIRLINES:
                if t in airline_raw.lower():
                    is_target = True
                    break

            if not is_target:
                continue

            clean_airline_name = get_airline_display_name(airline_raw)

            # --- Preis & Klassen Check ---
            price = flight.get('price', 0)
            if not price: continue

            # Sicherheitscheck Klasse (Textsuche)
            # Bei Business (Code 3) muss "business" irgendwo stehen
            t_class = first_leg.get('travel_class', '').lower()
            exts = str(first_leg.get('extensions', [])).lower()
            if cabin_code == "3" and ("business" not in t_class and "business" not in exts):
                continue

            # --- Daten speichern (Nur der günstigste pro Airline gewinnt) ---
            if clean_airline_name not in results_per_airline or price < results_per_airline[clean_airline_name]['price']:

                # Versuch, die Rückflug-Details zu erraten
                # Bei Roundtrips in der API ist das Mapping der Segmente schwierig.
                # Wir nehmen vereinfacht Startzeit Hinflug und Gesamtpreis.

                results_per_airline[clean_airline_name] = {
                    'airline': clean_airline_name,
                    'price': price,
                    'duration': flight.get('total_duration', 'N/A'),
                    'stops': len(flights_list) - 2, # Schätzung
                    'start_time': first_leg.get('departure_airport', {}).get('time', 'N/A'),
                    'cabin': cabin_name
                }

    except Exception as e:
        print(f"    ! Fehler: {e}")
        return []

    return list(results_per_airline.values())

def main():
    today = datetime.now()
    print(f"\n====== PREIS-MONITOR: {today.strftime('%d.%m.%Y')} ======")

    # Zeiträume berechnen
    d6_out = (today + timedelta(days=180)).strftime("%Y-%m-%d")
    d6_ret = (today + timedelta(days=180+21)).strftime("%Y-%m-%d") # +3 Wochen

    d10_out = (today + timedelta(days=300)).strftime("%Y-%m-%d")
    d10_ret = (today + timedelta(days=300+21)).strftime("%Y-%m-%d")

    dates_to_check = [
        ("6_Monate", d6_out, d6_ret),
        ("10_Monate", d10_out, d10_ret)
    ]

    # CSV Header
    fieldnames = [
        "Abfrage_Datum", "Zeitraum",
        "Start", "Ziel",
        "Hinflug_Datum", "Rueckflug_Datum",
        "Airline", "Klasse",
        "Hinflug_Preis", "Rueckflug_Preis", "GESAMTPREIS_EUR", # Die neuen Spalten
        "Dauer_Gesamt", "Abflugzeit_Hin"
    ]

    # CSV initialisieren
    file_exists = os.path.isfile(CSV_FILE)
    if not file_exists:
        with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

    results_buffer = []

    # --- HAUPTSCHLEIFE ---
    for origin in ORIGINS:
        for label, d_out, d_ret in dates_to_check:
            for cabin_name, cabin_code in CLASSES:

                found_flights = search_flights(origin, d_out, d_ret, cabin_name, cabin_code)

                if found_flights:
                    for flight in found_flights:
                        row = {
                            "Abfrage_Datum": today.strftime("%Y-%m-%d %H:%M"),
                            "Zeitraum": label,
                            "Start": origin,
                            "Ziel": DESTINATION,
                            "Hinflug_Datum": d_out,
                            "Rueckflug_Datum": d_ret,
                            "Airline": flight['airline'],
                            "Klasse": flight['cabin'],

                            # Hier die Logik: Einzelpreis gibt es nicht, nur Gesamtpreis
                            "Hinflug_Preis": "Paket",
                            "Rueckflug_Preis": "Paket",
                            "GESAMTPREIS_EUR": flight['price'],

                            "Dauer_Gesamt": flight['duration'],
                            "Abflugzeit_Hin": flight['start_time']
                        }
                        results_buffer.append(row)
                        print(f"    -> Treffer: {flight['airline']} ({cabin_name}) ab {origin}: {flight['price']} €")

                time.sleep(1.5) # Etwas langsamer, um API Fehler zu vermeiden

    # Speichern
    if results_buffer:
        with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            for row in results_buffer:
                writer.writerow(row)
        print(f"\nFertig! {len(results_buffer)} Ergebnisse in '{CSV_FILE}' gespeichert.")
    else:
        print("\nKeine Flüge gefunden.")

if __name__ == "__main__":
    main()