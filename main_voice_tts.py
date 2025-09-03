import os
from gtts import gTTS
import streamlit as st
from tempfile import NamedTemporaryFile

# This function replaces the assistant message display in start_conversation()
def speak_and_display(assistant_message):
    # Save and play audio
    try:
        tts = gTTS(text=assistant_message)
        with NamedTemporaryFile(delete=False, suffix=".mp3") as tmpfile:
            tts.save(tmpfile.name)
            st.audio(tmpfile.name, format="audio/mp3")
    except Exception as e:
        st.error(f"Failed to synthesize speech: {e}")
    
    # Display text
    st.markdown(f"**Customer:** {assistant_message}")
