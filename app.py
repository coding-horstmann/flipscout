import streamlit as st
import google.generativeai as genai
import requests
import json
import base64
from typing import List, Dict, Optional
import statistics
from io import BytesIO

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


def search_ebay_sold_items(query: str, max_results: int = 5) -> List[Dict]:
    """
    Sucht nach verkauften Artikeln auf eBay mit der Browse API
    """
    try:
        oauth_token = get_ebay_oauth_token()
        if not oauth_token:
            return []
        
        # eBay Browse API Endpoint für verkaufte Artikel
        # Nutze die Browse API mit Filter für verkaufte Artikel
        url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
        
        headers = {
            "Authorization": f"Bearer {oauth_token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_DE"
        }
        
        params = {
            "q": query,
            "limit": max_results * 2,  # Mehr Ergebnisse holen, da wir filtern müssen
            "filter": "conditions:{USED|VERY_GOOD|GOOD|ACCEPTABLE}"
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            items = data.get("itemSummaries", [])
            
            # Filtere nach verkauften Artikeln (wenn verfügbar)
            # Hinweis: Die Browse API zeigt nicht direkt "sold", daher nutzen wir
            # die verfügbaren Daten und filtern nach gebrauchten Artikeln
            sold_items = []
            for item in items[:max_results]:
                # Extrahiere Preisinformationen
                price_info = item.get("price", {})
                if price_info:
                    price_value = price_info.get("value", "0")
                    currency = price_info.get("currency", "EUR")
                    
                    # Konvertiere zu Float
                    try:
                        price_float = float(price_value)
                        sold_items.append({
                            "title": item.get("title", "Unbekannt"),
                            "price": price_float,
                            "currency": currency,
                            "itemId": item.get("itemId", ""),
                            "itemWebUrl": item.get("itemWebUrl", ""),
                            "condition": item.get("condition", "Unbekannt")
                        })
                    except ValueError:
                        continue
            
            return sold_items
        else:
            st.warning(f"⚠️ eBay API Fehler: {response.status_code}")
            if response.status_code == 401:
                st.error("❌ Ungültige eBay API Credentials!")
            return []
            
    except Exception as e:
        st.error(f"❌ Fehler bei eBay Suche: {str(e)}")
        return []


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
        
        # Verwende gemini-1.5-pro als stabiles Modell (falls nicht verfügbar, auf gemini-pro ändern)
        model = genai.GenerativeModel('gemini-1.5-pro')
        
        prompt = """Analysiere das Bild. Identifiziere alle Medienartikel (Bücher, Videospiele, DVDs, CDs, Blu-rays, etc.).

Gib mir NUR ein valides JSON Array zurück. Jedes Objekt muss das Feld 'query_text' enthalten (bestehend aus genauem Titel und Plattform/Autor für die beste eBay-Suche).

Beispiel-Format:
[
  {"query_text": "Harry Potter und der Stein der Weisen Buch"},
  {"query_text": "PlayStation 5 FIFA 23"},
  {"query_text": "Matrix DVD"}
]

WICHTIG: Gib NUR das JSON Array zurück, keine zusätzlichen Erklärungen oder Markdown."""

        # Lade das Bild
        image_data = {
            "mime_type": "image/jpeg",
            "data": image_bytes
        }
        
        response = model.generate_content([prompt, image_data])
        
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
                    
                    # eBay-Suche
                    ebay_items = search_ebay_sold_items(query, max_results=5)
                    
                    if ebay_items:
                        median_price = calculate_median_price(ebay_items)
                        if median_price:
                            results.append({
                                "Artikel": query,
                                "Median-Preis": f"{median_price:.2f} €",
                                "Link": ebay_items[0].get("itemWebUrl", ""),
                                "Preis": median_price
                            })
                    
                    progress_bar.progress((idx + 1) / len(detected_items))
                
                progress_bar.empty()
                status_text.empty()
                
                # Feature E: UI - Ergebnisse anzeigen
                if results:
                    st.header("📊 Ergebnisse")
                    
                    # Tabelle erstellen
                    display_results = []
                    for r in results:
                        display_results.append({
                            "Artikel": r["Artikel"],
                            "Median-Preis": r["Median-Preis"],
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
                        if r["Preis"] > 20:
                            st.success(f"✅ PROFIT: {r['Artikel']} - {r['Median-Preis']} 💚")
                        else:
                            st.info(f"ℹ️ {r['Artikel']} - {r['Median-Preis']}")
                else:
                    st.warning("⚠️ Keine eBay-Ergebnisse gefunden. Versuche es mit anderen Suchbegriffen.")

else:
    st.info("👆 Bitte lade ein Bild hoch oder mache ein Foto, um zu beginnen.")

# Footer
st.markdown("---")
st.markdown("**Flipscout** - Retail Arbitrage Scanner | Made with Streamlit")

