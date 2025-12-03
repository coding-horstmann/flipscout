import streamlit as st
import google.generativeai as genai
import requests
import json
import base64
from typing import List, Dict, Optional
import statistics
from io import BytesIO
from datetime import datetime

# Seite konfigurieren
st.set_page_config(
    page_title="Flipscout - Retail Arbitrage",
    page_icon="🔍",
    layout="wide"
)

# ============================================================================
# FEATURE A: SICHERHEIT (Türsteher)
# ============================================================================

def check_password():
    """Prüft das Passwort und speichert den Login-Status in session_state"""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if not st.session_state.authenticated:
        st.title("🔐 Flipscout Login")
        password = st.text_input("Passwort eingeben:", type="password")
        
        if st.button("Anmelden"):
            try:
                if password == st.secrets["APP_PASSWORD"]:
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("❌ Falsches Passwort!")
            except KeyError:
                st.error("❌ APP_PASSWORD nicht in secrets.toml gefunden!")
        
        st.stop()

# Passwort-Check vor allem anderen
check_password()

# ============================================================================
# HILFSFUNKTIONEN FÜR EBAY API
# ============================================================================

def get_ebay_oauth_token() -> Optional[str]:
    """
    Generiert einen OAuth Token für die eBay Browse API
    """
    try:
        app_id = st.secrets["EBAY_APP_ID"]
        cert_id = st.secrets["EBAY_CERT_ID"]
        
        # eBay OAuth Endpoint (Sandbox oder Production)
        # Für Production: https://api.ebay.com/identity/v1/oauth2/token
        oauth_url = "https://api.ebay.com/identity/v1/oauth2/token"
        
        # Credentials für Basic Auth
        credentials = f"{app_id}:{cert_id}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {encoded_credentials}"
        }
        
        data = {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope"
        }
        
        response = requests.post(oauth_url, headers=headers, data=data, timeout=10)
        
        if response.status_code == 200:
            token_data = response.json()
            return token_data.get("access_token")
        else:
            st.error(f"❌ Fehler beim OAuth Token: {response.status_code}")
            return None
            
    except KeyError as e:
        st.error(f"❌ Fehlender Secret: {e}")
        return None
    except Exception as e:
        st.error(f"❌ Fehler bei OAuth: {str(e)}")
        return None


def search_ebay_items(query: str, max_results: int = 50) -> Dict:
    """
    Sucht nach Artikeln auf eBay und sammelt umfassende Preisinformationen
    Gibt zurück: {
        'current_items': [],  # Aktuelle Angebote
        'sold_items': [],     # Verkaufte Artikel (falls verfügbar)
        'stats': {}           # Statistiken
    }
    """
    try:
        oauth_token = get_ebay_oauth_token()
        if not oauth_token:
            return {'current_items': [], 'sold_items': [], 'stats': {}}
        
        # 1. Aktuelle Angebote holen (Browse API)
        url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
        
        headers = {
            "Authorization": f"Bearer {oauth_token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_DE"
        }
        
        # Versuche zuerst mit Filter
        params = {
            "q": query,
            "limit": min(max_results, 200),
            "filter": "conditions:{USED|VERY_GOOD|GOOD|ACCEPTABLE}"
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        # Falls keine Ergebnisse, versuche ohne Filter
        if response.status_code == 200:
            data = response.json()
            items = data.get("itemSummaries", [])
            if not items:
                # Versuche ohne Filter
                params_no_filter = {
                    "q": query,
                    "limit": min(max_results, 200)
                }
                response = requests.get(url, headers=headers, params=params_no_filter, timeout=15)
        
        current_items = []
        if response.status_code == 200:
            data = response.json()
            items = data.get("itemSummaries", [])
            
            for item in items:
                price_info = item.get("price", {})
                if price_info:
                    price_value = price_info.get("value", "0")
                    currency = price_info.get("currency", "EUR")
                    
                    # Versandkosten extrahieren
                    shipping_cost = 0.0
                    shipping_options = item.get("shippingOptions", [])
                    if shipping_options:
                        # Nimm die erste Versandoption (meist günstigste)
                        first_shipping = shipping_options[0]
                        shipping_cost_info = first_shipping.get("shippingCost", {})
                        if shipping_cost_info:
                            shipping_cost_value = shipping_cost_info.get("value", "0")
                            try:
                                shipping_cost = float(shipping_cost_value)
                            except ValueError:
                                shipping_cost = 0.0
                    
                    try:
                        price_float = float(price_value)
                        price_with_shipping = price_float + shipping_cost
                        
                        current_items.append({
                            "title": item.get("title", "Unbekannt"),
                            "price": price_float,
                            "price_with_shipping": price_with_shipping,
                            "shipping_cost": shipping_cost,
                            "currency": currency,
                            "itemId": item.get("itemId", ""),
                            "itemWebUrl": item.get("itemWebUrl", ""),
                            "condition": item.get("condition", "Unbekannt"),
                            "availability": "available"
                        })
                    except ValueError:
                        continue
        else:
            # Debug-Informationen bei Fehler
            try:
                error_data = response.json()
                error_msg = str(error_data)[:500]  # Begrenze Länge
                st.error(f"❌ eBay API Fehler {response.status_code}: {error_msg}")
            except:
                error_text = response.text[:500] if hasattr(response, 'text') else str(response)
                st.error(f"❌ eBay API Fehler {response.status_code}: {error_text}")
        
        # Debug: Zeige Anzahl gefundener Items
        if not current_items:
            # Versuche eine einfachere Suche ohne Filter
            try:
                simple_params = {"q": query, "limit": 20}
                simple_response = requests.get(url, headers=headers, params=simple_params, timeout=15)
                if simple_response.status_code == 200:
                    simple_data = simple_response.json()
                    simple_items = simple_data.get("itemSummaries", [])
                    if simple_items:
                        # Verarbeite einfache Items ohne Filter
                        for item in simple_items:
                            price_info = item.get("price", {})
                            if price_info:
                                price_value = price_info.get("value", "0")
                                currency = price_info.get("currency", "EUR")
                                
                                shipping_cost = 0.0
                                shipping_options = item.get("shippingOptions", [])
                                if shipping_options:
                                    first_shipping = shipping_options[0]
                                    shipping_cost_info = first_shipping.get("shippingCost", {})
                                    if shipping_cost_info:
                                        shipping_cost_value = shipping_cost_info.get("value", "0")
                                        try:
                                            shipping_cost = float(shipping_cost_value)
                                        except ValueError:
                                            shipping_cost = 0.0
                                
                                try:
                                    price_float = float(price_value)
                                    price_with_shipping = price_float + shipping_cost
                                    
                                    current_items.append({
                                        "title": item.get("title", "Unbekannt"),
                                        "price": price_float,
                                        "price_with_shipping": price_with_shipping,
                                        "shipping_cost": shipping_cost,
                                        "currency": currency,
                                        "itemId": item.get("itemId", ""),
                                        "itemWebUrl": item.get("itemWebUrl", ""),
                                        "condition": item.get("condition", "Unbekannt"),
                                        "availability": "available"
                                    })
                                except ValueError:
                                    continue
            except Exception as e:
                pass  # Ignoriere Fehler bei Fallback-Suche
        
        # 2. Versuche Marketplace Insights API für Verkaufsdaten (letzte 90 Tage)
        sold_items = []
        try:
            insights_url = "https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search"
            insights_params = {
                "q": query,
                "filter": "conditions:{USED|VERY_GOOD|GOOD|ACCEPTABLE}"
            }
            
            insights_response = requests.get(
                insights_url, 
                headers=headers, 
                params=insights_params, 
                timeout=15
            )
            
            if insights_response.status_code == 200:
                insights_data = insights_response.json()
                # Verarbeite Insights-Daten falls verfügbar
                # Die Struktur kann variieren
                pass
        except:
            # Marketplace Insights API nicht verfügbar oder nicht autorisiert
            pass
        
        # 3. Berechne Statistiken (inklusive Versandkosten)
        stats = {}
        
        if current_items:
            # Sortiere Items nach Preis (inkl. Versand) für bessere Statistik
            current_items_sorted = sorted(current_items, key=lambda x: x["price_with_shipping"])
            
            # Preise mit Versandkosten für Statistiken
            current_prices_with_shipping = [item["price_with_shipping"] for item in current_items_sorted]
            
            stats['min_current_price'] = current_prices_with_shipping[0] if current_prices_with_shipping else None
            stats['median_current_price'] = statistics.median(current_prices_with_shipping) if current_prices_with_shipping else None
            stats['max_current_price'] = current_prices_with_shipping[-1] if current_prices_with_shipping else None
            stats['count_current'] = len(current_items)
            
            # Aktualisiere current_items mit sortierter Liste
            current_items = current_items_sorted
        
        if sold_items:
            sold_prices = [item["price"] for item in sold_items]
            sold_prices.sort()
            
            stats['min_sold_price'] = min(sold_prices)
            stats['median_sold_price'] = statistics.median(sold_prices) if sold_prices else None
            stats['count_sold'] = len(sold_items)
        
        return {
            'current_items': current_items,
            'sold_items': sold_items,
            'stats': stats
        }
        
    except Exception as e:
        st.error(f"❌ Fehler bei eBay Suche: {str(e)}")
        return {'current_items': [], 'sold_items': [], 'stats': {}}


def calculate_median_price(items: List[Dict]) -> Optional[float]:
    """Berechnet den Median-Preis aus einer Liste von Artikeln"""
    if not items:
        return None
    
    prices = [item["price"] for item in items if "price" in item]
    if not prices:
        return None
    
    return statistics.median(prices)


# ============================================================================
# FEATURE C: KI-ANALYSE MIT GEMINI
# ============================================================================

def analyze_image_with_gemini(image_bytes: bytes) -> List[Dict]:
    """
    Analysiert ein Bild mit Gemini und extrahiert Medienartikel
    """
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=api_key)
        
        # Versuche verschiedene Modellnamen (Fallback-Mechanismus)
        # Reihenfolge: Optimiert für kostenlose Nutzung mit hohen Limits
        # gemini-2.5-flash-lite hat 1000 RPD (statt 3 bei gemini-2.5-flash)
        model_names = [
            'models/gemini-2.5-flash-lite',  # BESTE OPTION: 1000 Requests/Tag, kostenlos!
            'models/gemini-2.0-flash-lite',   # Alternative: 200 RPD, sehr hohe Token-Limits
            'models/gemini-2.5-flash',        # Fallback: Nur 3 RPD in kostenloser Stufe
            'models/gemini-2.0-flash',        # Fallback: 200 RPD
            'models/gemini-2.5-pro',          # Fallback: Nur 50 RPD
        ]
        
        prompt = """Analysiere das Bild SEHR sorgfältig. Identifiziere ALLE Medienartikel (Bücher, Videospiele, DVDs, CDs, Blu-rays, etc.).

PRIORITÄT: Suche zuerst nach Barcodes und ISBNs!
- Erkenne Barcodes (Strichcodes) auf Büchern, DVDs, etc.
- Erkenne ISBN-Nummern (als Text, z.B. "ISBN 978-3-123-45678-9" oder "9783123456789")
- Erkenne EAN-Codes (13-stellige Zahlen unter Barcodes)
- Wenn Barcode/ISBN gefunden: Nutze diese für präzise Suche
- Wenn kein Barcode/ISBN: Lies den Titel

KRITISCH für Bücher von der Seite/Buchrücken:
- Lies den Text auf dem Buchrücken ZEICHEN FÜR ZEICHEN genau
- Suche nach ISBN-Nummern (oft am unteren Rand des Buchrückens)
- Wenn der Text unscharf oder schwer lesbar ist, sei EXTREM vorsichtig
- Verwechsle keine ähnlich aussehenden Buchstaben (z.B. "Miller's" nicht mit "Müller's")
- Prüfe jeden erkannten Titel mehrmals bevor du ihn aufnimmst
- Wenn du dir nicht sicher bist, gib den Text GENAU SO wieder wie er erscheint, auch wenn er unvollständig ist
- Kombiniere ALLE sichtbaren Informationen: Titel, Autor, Verlag, Untertitel, ISBN
- Bei Buchrücken: Lies von oben nach unten, achte auf Groß-/Kleinschreibung

Für alle Artikel:
- Wenn ISBN/Barcode vorhanden: Nutze diese (z.B. "ISBN 9783123456789" oder "EAN 4001234567890")
- Wenn kein Barcode: Nutze den vollständigen, EXAKTEN Titel wie er auf dem Artikel steht
- Füge Autor/Plattform hinzu für bessere eBay-Suche (nur wenn kein Barcode)
- Sei präzise: Nutze den genauen Titel (z.B. "Miller's Garden Antiques" nicht "Miller Garden Antique")

QUALITÄTSKONTROLLE:
- Prüfe jeden erkannten Titel auf Plausibilität
- Wenn ein Titel seltsam aussieht oder du dir unsicher bist, gib ihn trotzdem an, aber so genau wie möglich
- Bei Buchrücken: Lies den Text mehrmals und vergleiche
- Bei Barcodes: Prüfe ob die Zahlen vollständig sind

Gib mir NUR ein valides JSON Array zurück. Jedes Objekt muss das Feld 'query_text' enthalten.

Beispiel-Format (mit ISBN/Barcode bevorzugt):
[
  {"query_text": "ISBN 9783123456789"},
  {"query_text": "Harry Potter und der Stein der Weisen Buch"},
  {"query_text": "EAN 4001234567890"},
  {"query_text": "PlayStation 5 FIFA 23"},
  {"query_text": "Matrix DVD"},
  {"query_text": "Miller's Garden Antiques Buch"}
]

WICHTIG: 
- Gib NUR das JSON Array zurück, keine zusätzlichen Erklärungen oder Markdown
- PRIORISIERE Barcodes/ISBNs über Titel-Erkennung
- Bei Buchrücken: Lies den Text EXTREM sorgfältig, Zeichen für Zeichen
- Wenn unsicher: Gib den Text trotzdem an, aber so genau wie möglich"""

        # Lade das Bild
        image_data = {
            "mime_type": "image/jpeg",
            "data": image_bytes
        }
        
        # Versuche verschiedene Modelle, bis eines funktioniert
        response = None
        last_error = None
        successful_model = None
        
        for model_name in model_names:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content([prompt, image_data])
                successful_model = model_name
                break  # Erfolg, beende Schleife
            except Exception as e:
                last_error = str(e)
                continue
        
        if response is None:
            # Versuche verfügbare Modelle zu listen (für Debugging)
            try:
                available_models = [m.name for m in genai.list_models() 
                                  if 'generateContent' in m.supported_generation_methods]
                st.error(f"❌ Kein verfügbares Gemini-Modell gefunden. Letzter Fehler: {last_error}")
                st.info(f"💡 Verfügbare Modelle: {', '.join(available_models[:5])}")
            except:
                st.error(f"❌ Kein verfügbares Gemini-Modell gefunden. Letzter Fehler: {last_error}")
                st.info("💡 Bitte überprüfe deinen GOOGLE_API_KEY und die Modellverfügbarkeit.")
            return []
        
        # Extrahiere JSON aus der Antwort
        response_text = response.text.strip()
        
        # Entferne Markdown-Code-Blöcke falls vorhanden
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        
        response_text = response_text.strip()
        
        # Parse JSON
        try:
            items = json.loads(response_text)
            if isinstance(items, list):
                return items
            else:
                st.warning("⚠️ Gemini hat kein Array zurückgegeben")
                return []
        except json.JSONDecodeError as e:
            st.error(f"❌ Fehler beim Parsen der Gemini-Antwort: {str(e)}")
            st.code(response_text)
            return []
            
    except KeyError:
        st.error("❌ GOOGLE_API_KEY nicht in secrets.toml gefunden!")
        return []
    except Exception as e:
        st.error(f"❌ Fehler bei Gemini-Analyse: {str(e)}")
        return []


def get_alternative_search_terms(image_bytes: bytes, original_query: str) -> List[str]:
    """
    Fragt Gemini nach alternativen Suchbegriffen, wenn die ursprüngliche Suche keine Ergebnisse lieferte
    """
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=api_key)
        
        model_names = [
            'models/gemini-2.5-flash-lite',
            'models/gemini-2.0-flash-lite',
            'models/gemini-2.5-flash',
        ]
        
        retry_prompt = f"""Ich habe nach "{original_query}" auf eBay gesucht, aber keine Ergebnisse gefunden.

Analysiere das Bild nochmal und gib mir 2-3 alternative Suchbegriffe, die ich stattdessen probieren könnte.

Mögliche Gründe für fehlende Ergebnisse:
- Der Titel könnte anders geschrieben sein
- Es könnte ein anderer Autor/Plattform-Name sein
- Der Titel könnte verkürzt oder anders formuliert sein
- Es könnte ein ähnliches, aber anderes Produkt sein

Gib mir NUR ein valides JSON Array zurück mit alternativen Suchbegriffen.

Beispiel-Format:
[
  {"query_text": "Kürzerer Titel"},
  {"query_text": "Titel ohne Autor"},
  {"query_text": "Alternative Schreibweise"}
]

WICHTIG: 
- Gib NUR das JSON Array zurück, keine zusätzlichen Erklärungen
- Maximal 3 alternative Suchbegriffe
- Sei kreativ aber realistisch"""

        image_data = {
            "mime_type": "image/jpeg",
            "data": image_bytes
        }
        
        for model_name in model_names:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content([retry_prompt, image_data])
                
                # Extrahiere JSON aus der Antwort
                response_text = response.text.strip()
                
                # Entferne Markdown-Code-Blöcke falls vorhanden
                if response_text.startswith("```json"):
                    response_text = response_text[7:]
                if response_text.startswith("```"):
                    response_text = response_text[3:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
                
                response_text = response_text.strip()
                
                # Parse JSON
                try:
                    alternatives = json.loads(response_text)
                    if isinstance(alternatives, list):
                        # Extrahiere query_text aus jedem Objekt
                        search_terms = [alt.get("query_text", "") for alt in alternatives if alt.get("query_text")]
                        return search_terms[:3]  # Maximal 3 Alternativen
                except json.JSONDecodeError:
                    continue
                    
            except Exception:
                continue
        
        return []
        
    except Exception as e:
        return []


# ============================================================================
# HAUPTPROGRAMM
# ============================================================================

st.title("🔍 Flipscout - Retail Arbitrage Scanner")
st.markdown("---")

# Feature B: Input (Kamera UND File Uploader)
st.header("📸 Bild hochladen")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Kamera")
    camera_image = st.camera_input("Foto aufnehmen", label_visibility="collapsed")

with col2:
    st.subheader("Datei hochladen")
    uploaded_file = st.file_uploader(
        "Bilddatei auswählen",
        type=["jpg", "jpeg", "png"],
        label_visibility="collapsed"
    )

# Entscheide welches Bild verwendet wird
image_to_process = None
if camera_image:
    image_to_process = camera_image
elif uploaded_file:
    image_to_process = uploaded_file

if image_to_process:
    # Bild anzeigen
    st.image(image_to_process, caption="Hochgeladenes Bild", use_container_width=True)
    
    # Analysieren Button
    if st.button("🔍 Artikel analysieren", type="primary", use_container_width=True):
        with st.spinner("🤖 KI analysiert das Bild..."):
            # Bild in Bytes konvertieren
            image_bytes = image_to_process.read()
            
            # Gemini-Analyse
            detected_items = analyze_image_with_gemini(image_bytes)
            
            # Speichere image_bytes in session_state für Retry-Button
            st.session_state['current_image_bytes'] = image_bytes
            
            if not detected_items:
                st.warning("⚠️ Keine Artikel im Bild erkannt. Versuche es mit einem anderen Bild.")
                
                # Initialisiere Retry-Status für "nichts erkannt" Fall
                if 'retry_status' not in st.session_state:
                    st.session_state['retry_status'] = {}
                
                # Button für alternative Suche wenn nichts erkannt wurde
                no_item_key = "retry_no_item"
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write("**Keine Artikel erkannt** - Versuche alternative Suche")
                    
                    # Zeige Retry-Ergebnisse falls vorhanden
                    if no_item_key in st.session_state.get('retry_status', {}):
                        retry_info = st.session_state['retry_status'][no_item_key]
                        if retry_info.get('success'):
                            st.success(f"✅ **Erfolg mit:** {retry_info['query']}")
                            retry_result = {
                                "Artikel": retry_info['query'],
                                "Günstigster Angebotspreis (inkl. Versand)": f"{retry_info['min_price']:.2f} €",
                                "Median Angebotspreis (inkl. Versand)": f"{retry_info['median_price']:.2f} €",
                                "Link": retry_info['link']
                            }
                            st.dataframe([retry_result], use_container_width=True, hide_index=True)
                        elif retry_info.get('tried'):
                            st.warning(f"⚠️ Keine Ergebnisse für die Alternativen gefunden.")
                
                with col2:
                    # Button nur anzeigen wenn noch kein Erfolg
                    if no_item_key not in st.session_state.get('retry_status', {}) or not st.session_state['retry_status'][no_item_key].get('success'):
                        if st.button("🔄 Alternative suchen", key=f"btn_{no_item_key}"):
                            # Setze Flag für Retry
                            st.session_state['retry_status'][no_item_key] = {'processing': True}
                            st.rerun()
                
                # Führe Retry aus wenn Flag gesetzt ist
                if no_item_key in st.session_state.get('retry_status', {}) and st.session_state['retry_status'][no_item_key].get('processing'):
                    st.session_state['retry_status'][no_item_key]['processing'] = False
                    
                    retry_image_bytes = st.session_state.get('current_image_bytes')
                    if not retry_image_bytes:
                        st.error("❌ Bild nicht mehr verfügbar. Bitte analysiere das Bild erneut.")
                        st.session_state['retry_status'][no_item_key] = {'tried': True, 'success': False}
                    else:
                        st.info(f"🔄 **Starte alternative Suche...**")
                        
                        # Frage Gemini nach alternativen Suchbegriffen (ohne original_query, da nichts erkannt wurde)
                        with st.spinner("🤖 Analysiere Bild für alternative Suchbegriffe..."):
                            # Verwende einen generischen Prompt wenn nichts erkannt wurde
                            try:
                                api_key = st.secrets["GOOGLE_API_KEY"]
                                genai.configure(api_key=api_key)
                                
                                model_names = [
                                    'models/gemini-2.5-flash-lite',
                                    'models/gemini-2.0-flash-lite',
                                    'models/gemini-2.5-flash',
                                ]
                                
                                retry_prompt = """Analysiere das Bild und gib mir 2-3 Suchbegriffe für eBay, die ich probieren könnte.

Suche nach:
- Büchern (Titel, Autor, ISBN)
- Videospielen (Titel, Plattform)
- DVDs/Blu-rays (Titel)
- CDs (Künstler, Album)
- Anderen Medienartikeln

Gib mir NUR ein valides JSON Array zurück mit Suchbegriffen.

Beispiel-Format:
[
  {"query_text": "Buchtitel Autor"},
  {"query_text": "ISBN 9783123456789"},
  {"query_text": "Spiel Titel Plattform"}
]

WICHTIG: 
- Gib NUR das JSON Array zurück, keine zusätzlichen Erklärungen
- Maximal 3 Suchbegriffe
- Sei präzise und realistisch"""

                                image_data = {
                                    "mime_type": "image/jpeg",
                                    "data": retry_image_bytes
                                }
                                
                                alternative_queries = []
                                for model_name in model_names:
                                    try:
                                        model = genai.GenerativeModel(model_name)
                                        response = model.generate_content([retry_prompt, image_data])
                                        
                                        # Extrahiere JSON aus der Antwort
                                        response_text = response.text.strip()
                                        
                                        # Entferne Markdown-Code-Blöcke falls vorhanden
                                        if response_text.startswith("```json"):
                                            response_text = response_text[7:]
                                        if response_text.startswith("```"):
                                            response_text = response_text[3:]
                                        if response_text.endswith("```"):
                                            response_text = response_text[:-3]
                                        
                                        response_text = response_text.strip()
                                        
                                        # Parse JSON
                                        try:
                                            alternatives = json.loads(response_text)
                                            if isinstance(alternatives, list):
                                                # Extrahiere query_text aus jedem Objekt
                                                alternative_queries = [alt.get("query_text", "") for alt in alternatives if alt.get("query_text")]
                                                break
                                        except json.JSONDecodeError:
                                            continue
                                            
                                    except Exception:
                                        continue
                                
                                if alternative_queries:
                                    st.success(f"✅ **Gefundene Alternativen:** {', '.join(alternative_queries[:3])}")
                                    
                                    # Probiere alternative Suchbegriffe
                                    retry_success = False
                                    for idx_alt, alt_query in enumerate(alternative_queries, 1):
                                        if not alt_query:
                                            continue
                                        
                                        st.markdown(f"### 🔍 Versuch {idx_alt}: {alt_query}")
                                        
                                        with st.spinner(f"Suche bei eBay nach '{alt_query}'..."):
                                            ebay_data_retry = search_ebay_items(alt_query, max_results=50)
                                        
                                        stats_retry = ebay_data_retry.get('stats', {})
                                        current_items_retry = ebay_data_retry.get('current_items', [])
                                        
                                        # Nur als Erfolg werten wenn tatsächlich Items gefunden wurden
                                        if current_items_retry:
                                            # Erfolg! Speichere in session_state
                                            retry_success = True
                                            st.session_state['retry_status'][no_item_key] = {
                                                'success': True,
                                                'query': alt_query,
                                                'min_price': stats_retry.get('min_current_price', 0),
                                                'median_price': stats_retry.get('median_current_price', 0),
                                                'link': current_items_retry[0].get("itemWebUrl", "") if current_items_retry else ""
                                            }
                                            st.success(f"✅ **ERFOLG!** Gefunden mit: {alt_query}")
                                            st.rerun()
                                            break
                                        else:
                                            st.warning(f"❌ Keine Ergebnisse für: {alt_query}")
                                    
                                    if not retry_success:
                                        st.session_state['retry_status'][no_item_key] = {'tried': True, 'success': False}
                                        st.error("⚠️ **Keine der Alternativen hat Ergebnisse geliefert.**")
                                else:
                                    st.session_state['retry_status'][no_item_key] = {'tried': True, 'success': False}
                                    st.warning("⚠️ Keine Alternativen gefunden.")
                            except Exception as e:
                                st.error(f"❌ Fehler bei alternativer Suche: {str(e)}")
                                st.session_state['retry_status'][no_item_key] = {'tried': True, 'success': False}
            else:
                st.success(f"✅ {len(detected_items)} Artikel erkannt!")
                
                # Für jeden erkannten Artikel: eBay-Suche
                results = []
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for idx, item in enumerate(detected_items):
                    query = item.get("query_text", "")
                    if not query:
                        continue
                    
                    status_text.text(f"🔍 Suche nach: {query} ({idx + 1}/{len(detected_items)})")
                    
                    # eBay-Suche mit erweiterten Daten (50 Ergebnisse für bessere Statistik)
                    ebay_data = search_ebay_items(query, max_results=50)
                    
                    stats = ebay_data.get('stats', {})
                    current_items = ebay_data.get('current_items', [])
                    
                    # Nur als Erfolg werten wenn tatsächlich Items gefunden wurden
                    if current_items:
                        # Bereite Ergebnis-Daten vor
                        result_data = {
                            "Artikel": query,
                            "Günstigster Angebotspreis (inkl. Versand)": "N/A",
                            "Median Angebotspreis (inkl. Versand)": "N/A",
                            "Link": "",
                            "Preis": 0  # Für Profit-Berechnung
                        }
                        
                        # Aktuelle Angebote (inklusive Versandkosten)
                        if stats.get('min_current_price'):
                            result_data["Günstigster Angebotspreis (inkl. Versand)"] = f"{stats['min_current_price']:.2f} €"
                            result_data["Preis"] = stats['min_current_price']  # Für Profit-Berechnung
                        
                        if stats.get('median_current_price'):
                            result_data["Median Angebotspreis (inkl. Versand)"] = f"{stats['median_current_price']:.2f} €"
                        
                        # Link zum günstigsten Angebot (mit Versandkosten)
                        # current_items ist bereits nach Preis sortiert, daher ist das erste Element das günstigste
                        if current_items:
                            cheapest_item = current_items[0]  # Erstes Element ist das günstigste (bereits sortiert)
                            result_data["Link"] = cheapest_item.get("itemWebUrl", "")
                        
                        results.append(result_data)
                    else:
                        # Keine Ergebnisse gefunden - speichere für manuellen Retry
                        results.append({
                            "Artikel": query,
                            "Günstigster Angebotspreis (inkl. Versand)": "Keine Ergebnisse",
                            "Median Angebotspreis (inkl. Versand)": "Keine Ergebnisse",
                            "Link": "",
                            "Preis": 0,
                            "no_results": True,  # Flag für manuellen Retry
                            "original_query": query
                        })
                    
                    progress_bar.progress((idx + 1) / len(detected_items))
                
                progress_bar.empty()
                status_text.empty()
                
                # Feature E: UI - Ergebnisse anzeigen
                if results:
                    # Trenne Ergebnisse mit und ohne Daten
                    results_with_data = [r for r in results if not r.get("no_results", False)]
                    results_no_data = [r for r in results if r.get("no_results", False)]
                    
                    # Zeige Ergebnisse mit Daten
                    if results_with_data:
                        st.header("📊 Detaillierte Preisanalyse")
                        
                        display_results = []
                        for r in results_with_data:
                            display_results.append({
                                "Artikel": r["Artikel"],
                                "Günstigster Angebotspreis (inkl. Versand)": r["Günstigster Angebotspreis (inkl. Versand)"],
                                "Median Angebotspreis (inkl. Versand)": r["Median Angebotspreis (inkl. Versand)"],
                                "Link": r["Link"]
                            })
                        
                        st.dataframe(
                            display_results,
                            use_container_width=True,
                            hide_index=True
                        )
                        
                        # Erfolgsmeldungen für profitable Artikel
                        st.header("💰 Profit-Analyse")
                        for r in results_with_data:
                            median_offer = r.get("Median Angebotspreis (inkl. Versand)", "N/A")
                            min_offer = r.get("Günstigster Angebotspreis (inkl. Versand)", "N/A")
                            
                            # Profit-Bewertung basierend auf Median Angebotspreis (inkl. Versand)
                            if r["Preis"] > 20:
                                st.success(
                                    f"✅ **{r['Artikel']}** | "
                                    f"Günstigster: {min_offer} | "
                                    f"Median: {median_offer} | "
                                    f"Potentieller Profit: {r['Preis']:.2f}€+ 💚"
                                )
                            elif r["Preis"] > 10:
                                st.info(
                                    f"ℹ️ **{r['Artikel']}** | "
                                    f"Günstigster: {min_offer} | "
                                    f"Median: {median_offer} | "
                                    f"Möglicher Profit: {r['Preis']:.2f}€"
                                )
                            else:
                                st.warning(
                                    f"⚠️ **{r['Artikel']}** | "
                                    f"Günstigster: {min_offer} | "
                                    f"Median: {median_offer} | "
                                    f"Niedrige Margen"
                                )
                    
                    # Manuelle Retry-Option für Artikel ohne Ergebnisse
                    if results_no_data:
                        st.header("⚠️ Keine Ergebnisse gefunden")
                        
                        # Initialisiere Retry-Status in session_state
                        if 'retry_status' not in st.session_state:
                            st.session_state['retry_status'] = {}
                        
                        for r_idx, r in enumerate(results_no_data):
                            query_hash = str(hash(r['original_query']))
                            retry_key = f"retry_{r_idx}_{query_hash}"
                            
                            with st.container():
                                col1, col2 = st.columns([3, 1])
                                with col1:
                                    st.write(f"**{r['original_query']}** - Keine eBay-Ergebnisse gefunden")
                                    
                                    # Zeige Retry-Ergebnisse falls vorhanden
                                    if retry_key in st.session_state.get('retry_status', {}):
                                        retry_info = st.session_state['retry_status'][retry_key]
                                        if retry_info.get('success'):
                                            st.success(f"✅ **Erfolg mit:** {retry_info['query']}")
                                            retry_result = {
                                                "Artikel": retry_info['query'],
                                                "Günstigster Angebotspreis (inkl. Versand)": f"{retry_info['min_price']:.2f} €",
                                                "Median Angebotspreis (inkl. Versand)": f"{retry_info['median_price']:.2f} €",
                                                "Link": retry_info['link']
                                            }
                                            st.dataframe([retry_result], use_container_width=True, hide_index=True)
                                        elif retry_info.get('tried'):
                                            st.warning(f"⚠️ Keine Ergebnisse für die Alternativen gefunden.")
                                
                                with col2:
                                    # Button nur anzeigen wenn noch kein Erfolg
                                    if retry_key not in st.session_state.get('retry_status', {}) or not st.session_state['retry_status'][retry_key].get('success'):
                                        if st.button("🔄 Alternative suchen", key=f"btn_{retry_key}"):
                                            # Setze Flag für Retry
                                            st.session_state['retry_status'][retry_key] = {'processing': True}
                                            st.rerun()
                            
                            # Führe Retry aus wenn Flag gesetzt ist
                            if retry_key in st.session_state.get('retry_status', {}) and st.session_state['retry_status'][retry_key].get('processing'):
                                st.session_state['retry_status'][retry_key]['processing'] = False
                                
                                retry_image_bytes = st.session_state.get('current_image_bytes')
                                if not retry_image_bytes:
                                    st.error("❌ Bild nicht mehr verfügbar. Bitte analysiere das Bild erneut.")
                                    st.session_state['retry_status'][retry_key] = {'tried': True, 'success': False}
                                else:
                                    st.info(f"🔄 **Starte alternative Suche für:** {r['original_query']}")
                                    
                                    # Frage Gemini nach alternativen Suchbegriffen
                                    with st.spinner("🤖 Analysiere Bild für alternative Suchbegriffe..."):
                                        alternative_queries = get_alternative_search_terms(retry_image_bytes, r['original_query'])
                                    
                                    if alternative_queries:
                                        st.success(f"✅ **Gefundene Alternativen:** {', '.join(alternative_queries[:3])}")
                                        
                                        # Probiere alternative Suchbegriffe
                                        retry_success = False
                                        for idx_alt, alt_query in enumerate(alternative_queries, 1):
                                            if not alt_query or alt_query == r['original_query']:
                                                continue
                                            
                                            st.markdown(f"### 🔍 Versuch {idx_alt}: {alt_query}")
                                            
                                            with st.spinner(f"Suche bei eBay nach '{alt_query}'..."):
                                                ebay_data_retry = search_ebay_items(alt_query, max_results=50)
                                            
                                            stats_retry = ebay_data_retry.get('stats', {})
                                            current_items_retry = ebay_data_retry.get('current_items', [])
                                            
                                            # Nur als Erfolg werten wenn tatsächlich Items gefunden wurden
                                            if current_items_retry:
                                                # Erfolg! Speichere in session_state
                                                retry_success = True
                                                st.session_state['retry_status'][retry_key] = {
                                                    'success': True,
                                                    'query': alt_query,
                                                    'min_price': stats_retry.get('min_current_price', 0),
                                                    'median_price': stats_retry.get('median_current_price', 0),
                                                    'link': current_items_retry[0].get("itemWebUrl", "") if current_items_retry else ""
                                                }
                                                st.success(f"✅ **ERFOLG!** Gefunden mit: {alt_query}")
                                                st.rerun()
                                                break
                                            else:
                                                st.warning(f"❌ Keine Ergebnisse für: {alt_query}")
                                        
                                        if not retry_success:
                                            st.session_state['retry_status'][retry_key] = {'tried': True, 'success': False}
                                            st.error("⚠️ **Keine der Alternativen hat Ergebnisse geliefert.**")
                                    else:
                                        st.session_state['retry_status'][retry_key] = {'tried': True, 'success': False}
                                        st.warning("⚠️ Keine Alternativen gefunden.")
                            
                            st.markdown("---")
                else:
                    st.warning("⚠️ Keine eBay-Ergebnisse gefunden. Versuche es mit anderen Suchbegriffen.")

else:
    st.info("👆 Bitte lade ein Bild hoch oder mache ein Foto, um zu beginnen.")

# Footer
st.markdown("---")
current_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
st.markdown(f"**Flipscout** - Retail Arbitrage Scanner | Made with Streamlit | Version: {current_time}")

