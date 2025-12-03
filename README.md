# 🔍 Flipscout - Retail Arbitrage Scanner

Eine Streamlit-basierte Web-App zur Analyse von Medienartikeln (Bücher, Videospiele, DVDs) mit KI-gestützter Bilderkennung und automatischer eBay-Preisanalyse.

## Features

- 🔐 Passwort-geschützter Zugang
- 📸 Bild-Upload per Kamera oder Datei
- 🤖 KI-Analyse mit Google Gemini zur Erkennung von Medienartikeln
- 💰 Automatische eBay-Preissuche für verkaufte Artikel
- 📊 Median-Preisberechnung und Profit-Analyse

## Setup

1. Repository klonen
2. Dependencies installieren: `pip install -r requirements.txt`
3. Secrets konfigurieren: Kopiere `.streamlit/secrets.toml.example` zu `.streamlit/secrets.toml` und fülle die Werte aus
4. App starten: `streamlit run app.py`

## Deployment auf Streamlit Cloud

1. Verbinde dieses Repository mit Streamlit Cloud
2. Trage die Secrets in den Streamlit Cloud Settings ein
3. Die App wird automatisch deployed

## Technologien

- Streamlit
- Google Gemini AI
- eBay Browse API
- Python

