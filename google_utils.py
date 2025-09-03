import os
import json
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets"
]

def load_credentials():
    try:
        service_account_info = st.secrets["gcp_service_account"]
        return Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    except Exception as e:
        st.error(f"Failed to load Google credentials: {e}")
        raise

creds = load_credentials()

def get_sheet(sheet_name="BurgerXpress_Analytics"):
    try:
        import gspread
        gc = gspread.authorize(creds)
        return gc.open(sheet_name).sheet1
    except Exception as e:
        st.error(f"Error accessing Google Sheet: {e}")
        raise

def append_to_sheet(data: list, sheet_name="BurgerXpress_Analytics"):
    try:
        sheet = get_sheet(sheet_name)
        sheet.append_row(data)
        st.success("✅ Logged conversation to Google Sheet")
    except Exception as e:
        st.error(f"Error appending data to Google Sheet: {e}")
        raise

def upload_to_drive(file_path, folder_id=None):
    try:
        service = build("drive", "v3", credentials=creds)
        file_metadata = {"name": os.path.basename(file_path)}
        if folder_id:
            file_metadata["parents"] = [folder_id]
        media = MediaFileUpload(file_path, mimetype="text/plain")
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink"
        ).execute()
        st.success("✅ Conversation uploaded to Google Drive")
        st.markdown(f"🔗 [View File]({uploaded.get('webViewLink')})")
        return uploaded.get("webViewLink")
    except Exception as e:
        st.error(f"Failed to upload file to Google Drive: {e}")
        raise

def list_files_in_folder(folder_id, mime_type='text/plain'):
    try:
        service = build('drive', 'v3', credentials=creds)
        query = f"'{folder_id}' in parents and mimeType='{mime_type}' and trashed=false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        return results.get('files', [])
    except Exception as e:
        st.error(f"Error listing files in Google Drive folder: {e}")
        return []