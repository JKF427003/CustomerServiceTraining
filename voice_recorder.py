import streamlit as st
from streamlit_webrtc import webrtc_streamer, AudioProcessorBase, WebRtcMode
import numpy as np
import av
import queue
import tempfile
import os
from pydub import AudioSegment

# For capturing audio frames
class AudioProcessor(AudioProcessorBase):
    def __init__(self):
        self.recorded_frames = []
        self.q = queue.Queue()

    def recv_audio(self, frame: av.AudioFrame) -> av.AudioFrame:
        audio = frame.to_ndarray()
        self.q.put(audio)
        return frame

    def get_audio_data(self):
        all_frames = []
        while not self.q.empty():
            all_frames.append(self.q.get())
        return np.concatenate(all_frames, axis=1) if all_frames else None

# Helper function to convert audio to file
def save_audio_as_wav(audio_data, sample_rate=48000):
    if audio_data is None:
        return None
    temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    segment = AudioSegment(
        audio_data.tobytes(),
        frame_rate=sample_rate,
        sample_width=2,  # bytes per sample (16-bit)
        channels=1
    )
    segment.export(temp_wav.name, format="wav")
    return temp_wav.name

# UI and logic for recording
def record_voice_message():
    st.subheader("🎙️ Record Your Response")
    webrtc_ctx = webrtc_streamer(
    key="voice",
    mode=WebRtcMode.SENDONLY,  # ✅ Fix here
    audio_receiver_size=1024,
    media_stream_constraints={"audio": True, "video": False},
    async_processing=True,
    audio_processor_factory=AudioProcessor,
)

    audio_file_path = None
    if webrtc_ctx.audio_processor:
        if st.button("Stop and Save Recording"):
            raw_audio = webrtc_ctx.audio_processor.get_audio_data()
            audio_file_path = save_audio_as_wav(raw_audio)
            if audio_file_path:
                st.success("Recording saved. Transcribing...")
    return audio_file_path
