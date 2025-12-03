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
        
        params = {
            "q": query,
            "limit": min(max_results, 200),  # Mehr Ergebnisse für bessere Statistik
            "filter": "conditions:{USED|VERY_GOOD|GOOD|ACCEPTABLE}"
        }
        
        # Versuche zuerst ohne Sortierung (falls Sortierung nicht unterstützt wird)
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        current_items = []
        if response.status_code == 200:
            data = response.json()
            items = data.get("itemSummaries", [])
            
            # Debug: Prüfe ob Items gefunden wurden
            if not items:
                # Versuche ohne Filter, falls Filter zu restriktiv ist
                params_no_filter = {
                    "q": query,
                    "limit": min(max_results, 200)
                }
                response_no_filter = requests.get(url, headers=headers, params=params_no_filter, timeout=15)
                if response_no_filter.status_code == 200:
                    data_no_filter = response_no_filter.json()
                    items = data_no_filter.get("itemSummaries", [])
            
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

KRITISCH für Bücher von der Seite/Buchrücken:
- Lies den Text auf dem Buchrücken ZEICHEN FÜR ZEICHEN genau
- Wenn der Text unscharf oder schwer lesbar ist, sei EXTREM vorsichtig
- Verwechsle keine ähnlich aussehenden Buchstaben (z.B. "Miller's" nicht mit "Müller's")
- Prüfe jeden erkannten Titel mehrmals bevor du ihn aufnimmst
- Wenn du dir nicht sicher bist, gib den Text GENAU SO wieder wie er erscheint, auch wenn er unvollständig ist
- Kombiniere ALLE sichtbaren Informationen: Titel, Autor, Verlag, Untertitel
- Bei Buchrücken: Lies von oben nach unten, achte auf Groß-/Kleinschreibung

Für alle Artikel:
- Nutze den vollständigen, EXAKTEN Titel wie er auf dem Buch steht
- Füge Autor/Plattform hinzu für bessere eBay-Suche
- Sei präzise: Nutze den genauen Titel (z.B. "Miller's Garden Antiques" nicht "Miller Garden Antique")

QUALITÄTSKONTROLLE:
- Prüfe jeden erkannten Titel auf Plausibilität
- Wenn ein Titel seltsam aussieht oder du dir unsicher bist, gib ihn trotzdem an, aber so genau wie möglich
- Bei Buchrücken: Lies den Text mehrmals und vergleiche

Gib mir NUR ein valides JSON Array zurück. Jedes Objekt muss das Feld 'query_text' enthalten.

Beispiel-Format:
[
  {"query_text": "Harry Potter und der Stein der Weisen Buch"},
  {"query_text": "PlayStation 5 FIFA 23"},
  {"query_text": "Matrix DVD"},
  {"query_text": "Miller's Garden Antiques Buch"}
]

WICHTIG: 
- Gib NUR das JSON Array zurück, keine zusätzlichen Erklärungen oder Markdown
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
            
            if not detected_items:
                st.warning("⚠️ Keine Artikel im Bild erkannt. Versuche es mit einem anderen Bild.")
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
                    
                    if stats or current_items:
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
                    
                    progress_bar.progress((idx + 1) / len(detected_items))
                
                progress_bar.empty()
                status_text.empty()
                
                # Feature E: UI - Ergebnisse anzeigen
                if results:
                    st.header("📊 Detaillierte Preisanalyse")
                    
                    # Erweiterte Tabelle mit allen Daten
                    display_results = []
                    for r in results:
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
                    for r in results:
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
                else:
                    st.warning("⚠️ Keine eBay-Ergebnisse gefunden. Versuche es mit anderen Suchbegriffen.")

else:
    st.info("👆 Bitte lade ein Bild hoch oder mache ein Foto, um zu beginnen.")

# Footer
st.markdown("---")
current_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
st.markdown(f"**Flipscout** - Retail Arbitrage Scanner | Made with Streamlit | Version: {current_time}")

