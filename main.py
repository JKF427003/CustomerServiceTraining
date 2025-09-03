import streamlit as st
import os
import datetime
from dotenv import load_dotenv
import openai
import json
from PIL import Image
import pandas as pd
import re
import random
from google_utils import get_sheet
from google_utils import creds
from google_utils import upload_to_drive, append_to_sheet
from main_voice_tts import speak_and_display
from voice_recorder import record_voice_message
import tempfile
from gtts import gTTS
import plotly.express as px

#Styling
st.set_page_config(page_title="Customer Service Training", page_icon="🍟", layout="wide")

st.markdown("""
<style>
/* DARK MODE */
@media (prefers-color-scheme: dark) {
    [data-testid="stSidebar"] {
        background-color: #1e1e1e !important;
        color: #f0f0f0 !important;
        border-right: 1px solid #444;
    }
    [data-testid="stSidebar"] * {
        color: #f0f0f0 !important;
    }
    [data-testid="stSidebar"] a {
        color: #8ab4f8 !important;
    }
    button {
        background-color: #333 !important;
        color: #f0f0f0 !important;
    }
}

/* LIGHT MODE (refined to clean white) */
@media (prefers-color-scheme: light) {
    [data-testid="stSidebar"] {
        background-color: #ffffff !important;
        color: #1f1f1f !important;
        border-right: 1px solid #e0e0e0;
    }
    [data-testid="stSidebar"] * {
        color: #1f1f1f !important;
    }
    [data-testid="stSidebar"] a {
        color: #1a73e8 !important;
    }
    button {
        background-color: #f9f9f9 !important;
        color: #1f1f1f !important;
        border: 1px solid #dcdcdc !important;
    }
}
</style>


""", unsafe_allow_html=True)

def plotly_bar_chart(series, title):
    import plotly.express as px
    if not isinstance(series, pd.Series):
        st.warning("Invalid input to plotly_bar_chart. Must be a single Series.")
        return
    counts = series.value_counts().sort_index()
    fig = px.bar(
        x=counts.index.astype(str),
        y=counts.values,
        labels={'x': series.name or 'Category', 'y': 'Count'},
        color=counts.index.astype(str),
        title=title
    )
    st.plotly_chart(fig, use_container_width=True)

#Calling Folders on Google Drive
FOLDER_CONVERSATIONS = "1bgLn49otCu9G7lP8XgkCdGPNDRm70hKX"
FOLDER_TESTING = "1PD0VBVIyJIZPIcvE7h4sFwj02irgTrfL"

# Load environment variables
load_dotenv()
openai_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

if not openai_key:
    raise ValueError("❌ OPENAI_API_KEY not found. Please add it to Streamlit secrets or .env")

openai.api_key = openai_key

# Initialize OpenAI client
MODEL = 'gpt-4o'

# Load menu data
def load_menu():
    with open("data/menu.json", "r") as file:
        return json.load(file)
    
# Load Customer Guidelines
def load_rules():
    with open("data/rules.json", "r") as file:
        return json.load(file)

def load_scenarios():
    with open("data/scenarios.json", "r") as file:
        return json.load(file)

menu = load_menu()
rules = load_rules()

# System message to define the AI's role
# Load scenarios
scenarios_data = load_scenarios()

# Initialize session state for navigation and conversation
if "page" not in st.session_state:
    st.session_state.page = "Main Menu"  # Default page
if "conversation_history" not in st.session_state:
    st.session_state.conversation_history = []
if "show_feedback" not in st.session_state:
    st.session_state.show_feedback = False
if "selected_conversation" not in st.session_state:
    st.session_state.selected_conversation = None
if "testing_mode" not in st.session_state:
    st.session_state.testing_mode = False

# Function to save conversation history and feedback
def save_conversation(history, feedback):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H-%M-%S')
    filename = f"conversation_{timestamp}.txt"
    file_path = os.path.join(os.getcwd(), filename)

    # Initialize analytics
    employee_msgs = 0
    customer_msgs = 0
    escalation_keywords = ["manager", "escalate", "supervisor", "complain", "issue"]
    escalation_flag = "No"

    with open(file_path, "w", encoding="utf-8") as file:
        file.write("=== Conversation History ===\n")
        for entry in history:
            role = entry['role'].capitalize()
            content = entry['content']
            file.write(f"{role}: {content}\n")

            if role == "Employee":
                employee_msgs += 1
            elif role == "Customer":
                customer_msgs += 1

            if any(keyword in content.lower() for keyword in escalation_keywords):
                escalation_flag = "Yes"

        file.write("\n=== Coaching Feedback ===\n")

        scores = st.session_state.get("scores", {})
        file.write("\n=== AI Scoring ===\n")
        for key, val in scores.items():
            file.write(f"{key}: {val}\n")

        file.write(feedback)

        rating = st.session_state.get("feedback_rating")
        feedback_text = st.session_state.get("feedback_text", "")
        issue_description = st.session_state.get("issue_description", "")

        if rating:
            file.write(f"\n\n=== Feedback Rating ===\n{rating}/5")
        if feedback_text:
            file.write(f"\n\n=== Written Feedback ===\n{feedback_text}")
        if issue_description:
            file.write(f"\n\n=== Issue Description ===\n{issue_description}")

    # Upload to Google Drive
    folder_id = FOLDER_TESTING if st.session_state.testing_mode else FOLDER_CONVERSATIONS
    drive_url = upload_to_drive(file_path, folder_id)

    # Log all data to Google Sheets
    scores = st.session_state.get("scores", {})
    append_to_sheet([
        filename,
        timestamp,
        rating or "N/A",
        drive_url,
        employee_msgs,
        customer_msgs,
        len(history),
        escalation_flag,
        scores.get("Rule Compliance", "N/A"),
        scores.get("Escalation Handling", "N/A"),
        scores.get("Professionalism", "N/A"),
        scores.get("Clarity", "N/A")
    ])

    return filename

# Function to generate coaching feedback
def generate_coaching_feedback(history):
    if len(history) < 3:
        return {
            "summary": "Conversation was too short to generate useful coaching feedback.",
            "scores": {
                "Rule Compliance": "N/A",
                "Escalation Handling": "N/A",
                "Professionalism": "N/A",
                "Clarity": "N/A"
            }
        }

    coaching_prompt = (
        "You are a customer service coach analyzing a spoken conversation between an employee and a customer. "
        "Focus on the employee's professionalism, clarity, tone, and escalation decisions — not grammar or punctuation. "
        "The employee is speaking, not writing.\n\n"
        "Return coaching feedback as a bullet-pointed list. Each point should be clear and reference the employee's actions or language. "
        "Include one point per score category, with explanation and the score at the end like this:\n"
        "- **Rule Compliance**: [explanation] (Score: 4/5)\n"
        "- **Escalation Handling**: [explanation] (Score: Pass)\n"
        "- **Professionalism**: [explanation] (Score: 3/5)\n"
        "- **Clarity**: [explanation] (Score: 5/5)\n\n"
        "At the end of your feedback, include a clear breakdown of the scores again, exactly like this:\n\n"
        "=== Scores ===\n"
        "Rule Compliance: 4\n"
        "Escalation Handling: Pass\n"
        "Professionalism: 3\n"
        "Clarity: 5\n\n"
        "Here is the conversation:\n" +
        "\n".join([f"{entry['role'].capitalize()}: {entry['content']}" for entry in history])
    )

    try:
        response = openai.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": coaching_prompt}],
            stream=False
        )
        content = response.choices[0].message.content.strip()

        summary, scores_block = content.split("=== Scores ===")
        scores_lines = scores_block.strip().splitlines()
        scores = {}
        for line in scores_lines:
            if ":" in line:
                key, val = line.split(":", 1)
                scores[key.strip()] = val.strip()

        return {
            "summary": summary.strip(),
            "scores": scores
        }
    except Exception as e:
        return {
            "summary": f"An error occurred: {e}",
            "scores": {
                "Rule Compliance": "N/A",
                "Escalation Handling": "N/A",
                "Professionalism": "N/A",
                "Clarity": "N/A"
            }
        }

# Function to reset the session state
def reset_session():
    st.session_state.conversation_history = []
    st.session_state.show_feedback = False
    st.session_state.selected_conversation = None
    st.session_state.pop("chosen_scenario", None)
    st.session_state.pop("chosen_personality", None)

# Main Menu Page
def main_menu():
    st.title("🍔 Welcome to BurgerXpress Training")

    st.markdown("Choose an action below:")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📘 Instructions"):
            st.session_state.page = "Instructions"
            st.rerun()
    with col2:
        if st.button("🗣️ Start Conversation"):
            st.session_state.page = "Start Conversation"
            st.rerun()
    with col3:
        if st.button("📝 General Feedback"):
            st.session_state.page = "General Feedback"
            st.rerun()

    st.markdown("___")
    st.markdown("Use the sidebar to access more features or settings.")

# System message to define the AI's role
def format_conversation_for_openai(convo):
    """Convert internal roles to valid OpenAI roles."""
    chosen_scenario = st.session_state.get("chosen_scenario", "[Unknown scenario]")
    chosen_personality = st.session_state.get("chosen_personality", "[Unknown personality]")

    system_message = (
        f"You are a {chosen_personality} customer at BurgerXpress. "
        f"Your issue is: '{chosen_scenario}'\n"
        "React naturally with tone and behavior that matches your personality. "
        "Use the menu to support your complaint. "
        "If the situation escalates too much and the employee is crew, they should call a manager.\n"
        "Here is the menu data:\n\n" + json.dumps(menu, indent=2)
    )

    messages = [{"role": "system", "content": system_message}]
    for entry in convo:
        if entry["role"] == "employee":
            messages.append({"role": "user", "content": entry["content"]})
        elif entry["role"] == "customer":
            messages.append({"role": "assistant", "content": entry["content"]})
    return messages

# Start Conversation Page
def start_conversation():
    if "chosen_scenario" not in st.session_state:
        st.session_state.chosen_scenario = random.choice(scenarios_data["scenarios"])
    if "chosen_personality" not in st.session_state:
        st.session_state.chosen_personality = random.choice(scenarios_data["personalities"])

    if not st.session_state.conversation_history:
        chosen_scenario = st.session_state.chosen_scenario
        chosen_personality = st.session_state.chosen_personality

        st.info(f"🤖 Scenario: *{chosen_scenario}*  \n**Personality:** {chosen_personality}")

        init_message = "Hi, can I speak to someone about an issue with my order?"
        st.session_state.conversation_history.append({"role": "customer", "content": init_message})
        
        if init_message.strip():
            try:
                tts = gTTS(text=init_message)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmpfile:
                    tts.save(tmpfile.name)
                    st.audio(tmpfile.name, format="audio/mp3")
            except Exception as e:
                st.error(f"Failed to synthesize speech: {e}")
        else:
            st.warning("No audio generated (message was empty).")

    use_voice = st.toggle("🎙️ Use microphone input instead of typing?", value=False)

    for entry in st.session_state.conversation_history:
        role = entry["role"]
        name = "Customer" if role == "customer" else "Employee"
        avatar = "🍔" if role == "customer" else "😎"
        with st.chat_message(name, avatar=avatar):
            st.markdown(entry["content"])

    if not st.session_state.get("show_feedback", False):
        user_input = None
        if use_voice:
            audio_path = record_voice_message()
            if audio_path:
                try:
                    with open(audio_path, "rb") as audio_file:
                        transcript = openai.Audio.transcribe("whisper-1", audio_file)
                        user_input = transcript["text"]
                        st.markdown(f"**You said:** {user_input}")
                except Exception as e:
                    st.error(f"Transcription failed: {e}")
                    user_input = None
        else:
            user_input = st.chat_input("Your response:")

        col1, col2 = st.columns(2)
        with col1:
            if user_input:
                st.session_state.conversation_history.append({"role": "employee", "content": user_input})
                messages = format_conversation_for_openai(st.session_state.conversation_history)

                try:
                    stream = openai.chat.completions.create(model=MODEL, messages=messages, stream=True)
                    assistant_message = ""
                    for chunk in stream:
                        text = chunk.choices[0].delta.content or ''
                        assistant_message += text

                    st.session_state.conversation_history.append({"role": "customer", "content": assistant_message})

                    with st.chat_message("assistant", avatar="🍔"):
                        st.markdown(assistant_message)
                        if assistant_message.strip():
                            try:
                                tts = gTTS(text=assistant_message)
                                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmpfile:
                                    tts.save(tmpfile.name)
                                    st.audio(tmpfile.name, format="audio/mp3")
                            except Exception as e:
                                st.error(f"Failed to synthesize speech: {e}")
                        else:
                            st.warning("No audio generated (message was empty).")
                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")

        with col2:
            if st.button("❌ Exit Conversation"):
                st.session_state.pending_exit = True
                st.rerun()

    if st.session_state.get("pending_exit", False):
        st.warning("Are you sure you want to end the conversation?")
        if st.button("✅ Yes, End and Get Feedback"):
            st.session_state.show_feedback = True
            st.session_state.pending_exit = False
            feedback_result = generate_coaching_feedback(st.session_state.conversation_history)
            st.session_state.feedback = feedback_result["summary"]
            st.session_state.scores = feedback_result["scores"]
            st.rerun()
        if st.button("⬅️ Cancel"):
            st.session_state.pending_exit = False
            st.rerun()

    if st.session_state.get("show_feedback", False):
        st.write("### Coaching Feedback")
        for line in st.session_state.feedback.splitlines():
            if line.strip().startswith("-"):
                st.markdown(line.strip())
            else:
                st.markdown(line.strip())

        with st.form("post_chat_feedback_form"):
            feedback_text = st.text_area("Your Feedback", placeholder="Describe your experience...", height=150)
            rating = st.slider("Rate the experience", 1, 5, key="feedback_rating")
            submitted = st.form_submit_button("✅ Submit Feedback")

        issue_description = ""
        if submitted:
            report_issue = st.toggle("Do you want to report an issue?")
            if report_issue:
                issue_description = st.text_area("Describe the Issue", placeholder="Provide details about the issue...")

            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            filename = f"conversation_{timestamp.replace(':', '-')}.txt"
            file_path = os.path.join(os.getcwd(), filename)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write("=== Conversation History ===\n")
                for entry in st.session_state.conversation_history:
                    f.write(f"{entry['role'].capitalize()}: {entry['content']}\n")
                f.write("\n=== Coaching Feedback ===\n")
                f.write(st.session_state.feedback)
                f.write(f"\n\n=== Feedback Rating ===\n{rating}/5\n")
                f.write(f"\n=== Written Feedback ===\n{feedback_text}\n")
                if issue_description:
                    f.write(f"\n=== Issue Reported ===\n{issue_description}\n")

            if not st.session_state.testing_mode:
                save_conversation(st.session_state.conversation_history, st.session_state.feedback)
                st.toast(f"Saved: {filename}")

            st.session_state.filename = filename
            st.session_state.submitted = True
            st.success("Conversation and feedback submitted successfully.")

        if st.button("🏠 Return to Home"):
            reset_session()
            st.session_state.page = "Main Menu"
            st.rerun()
    
# Show Menu Page
def show_menu():
    st.title("BurgerXpress Menu")
    st.write("#### A La Carte")
    for item in menu["menu"]["a_la_carte"]:
        st.write(f"- **{item['name']}**: {item['description']}")
    st.write("#### Kids Menu")
    for item in menu["menu"]["kids_menu"]["food_options"]:
        st.write(f"- **{item['name']}**: {item['description']}")
    st.write("#### Meals")
    for item in menu["menu"]["meals"]["options"]:
        st.write(f"- **{item['name']}**: {item['description']}")

    if st.button("Back to Main Menu"):
        st.session_state.page = "Main Menu"
        st.rerun()

# Instructions Page
def instructions():
    st.title("📘 Instructions")

    st.markdown("""
    ### 👩‍🍳 How to Use the App

    1. Go to **Start Conversation** to begin interacting with a simulated customer.
    2. The customer will have a **scenario** and a **personality** — these are shown at the top of the screen.
    3. You can respond either by **typing** or using the **microphone**.
    4. Your role is to provide excellent customer service, addressing the issue calmly and professionally.
    5. If the situation begins to **escalate**, and you feel it's too much to handle:
       - You should respond with something like:  
         `"Let me get a manager to help you with that."`
       - Then you may click **❌ Exit Conversation**.
       - The AI will give one last reply, and you'll receive feedback.
    6. When you exit the conversation, you'll be shown **coaching feedback**.
    7. After reviewing it, fill out the **feedback form**, then click **✅ Submit Feedback** to log your session.
    8. You can view analytics later under the **Analytics** tab.

    ---
    🔁 You can restart a new session by clicking **Return to Home** after any conversation.
    """)

    if st.button("Back to Main Menu"):
        st.session_state.page = "Main Menu"
        st.rerun()

# Service Guidlines
def service_guidelines():
    st.title("Customer Service Guidelies")
    st.write("### Customer Service Rules")
    for key, rule in rules['customer_service_rules'].items():
        st.markdown(f"**{key.replace('_',' ').title()}**: {rule}")
    st.write("### Managerial Escalation Guidelines")
    for key, guideline in rules['managerial_escalation_guidelines'].items():
        st.markdown(f"**{key.replace('_',' ').title()}**: {guideline}")
    
    if st.button("Back to Main Menu"):
        st.session_state.page = "Main Menu"
        st.rerun()

# Past Conversations Page
def past_conversations():
    from google_utils import list_files_in_folder
    from googleapiclient.discovery import build

    st.title("Past Conversations (Google Drive)")

    try:
        files = list_files_in_folder(FOLDER_CONVERSATIONS)
        if not files:
            st.info("No conversation files found in Google Drive.")
            return

        file_names = [f["name"] for f in files]
        file_dict = {f["name"]: f["id"] for f in files}

        selected_file_name = st.selectbox("Select a conversation to preview:", file_names)

        if selected_file_name:
            file_id = file_dict[selected_file_name]
            service = build("drive", "v3", credentials=creds)
            request = service.files().get_media(fileId=file_id)

            import io
            from googleapiclient.http import MediaIoBaseDownload

            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            fh.seek(0)
            content = fh.read().decode("utf-8")

            st.text_area("Conversation Preview", content, height=400)

            st.download_button(
                label="⬇️ Download Conversation",
                data=content,
                file_name=selected_file_name,
                mime="text/plain"
            )

    except Exception as e:
        st.error(f"Failed to load past conversations from Google Drive: {e}")

# Analytics Dashboard Page
def analytics_dashboard():
    st.title("📊 Analytics Dashboard")

    dashboard_type = st.selectbox("Choose Analytics Type", ["Conversation Analytics", "Feedback Analytics"])

    try:
        import gspread
        from google.oauth2.service_account import Credentials
        import pandas as pd

        service_account_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(service_account_info, scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ])
        gc = gspread.authorize(creds)

        if dashboard_type == "Conversation Analytics":
            sheet = gc.open("BurgerXpress_Analytics").sheet1
            records = sheet.get_all_records()
            df = pd.DataFrame(records)
            if df.empty:
                st.info("No conversation data available.")
                return

            df["Timestamp"] = pd.to_datetime(df.get("Timestamp"), format="%Y-%m-%d %H-%M-%S", errors="coerce")
            df = df[df["Timestamp"].notnull()]
            df["Rating"] = pd.to_numeric(df.get("Rating"), errors="coerce")
            df["Employee Messages"] = pd.to_numeric(df.get("Employee Messages"), errors="coerce").fillna(0)
            df["Customer Messages"] = pd.to_numeric(df.get("Customer Messages"), errors="coerce").fillna(0)
            df["Conversation Length"] = pd.to_numeric(df.get("Conversation Length"), errors="coerce").fillna(0)
            df["Escalation"] = df.get("Escalation", "No").fillna("No")

            st.subheader("📈 Summary Stats")
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Conversations", len(df))
            col2.metric("Avg Feedback Rating", f"{df['Rating'].mean():.2f}")
            col3.metric("Avg Conversation Length", f"{df['Conversation Length'].mean():.0f} messages")

            st.subheader("📅 Conversations Over Time")
            st.line_chart(df.groupby(df["Timestamp"].dt.date).size())

            #st.subheader("⭐ Rating Distribution")
            plotly_bar_chart(df["Rating"], title="Experience Ratings")

            st.subheader("🧾 Total Messages by Role")
            st.bar_chart({
                "Employee": df["Employee Messages"].sum(),
                "Customer": df["Customer Messages"].sum(),
            })

            st.subheader("🚨 Escalation Summary")
            escalation_rate = (df["Escalation"] == "Yes").sum() / len(df) * 100
            st.metric("Escalation Rate", f"{escalation_rate:.1f}%")

            st.subheader("📊 Coaching Scores")
            for field in ["Rule Compliance", "Professionalism", "Clarity"]:
                df[field] = pd.to_numeric(df.get(field), errors="coerce")
            df["Escalation Handling"] = df.get("Escalation Handling", "N/A")
            score_trend = df.set_index("Timestamp").resample("W").mean(numeric_only=True)[["Rule Compliance", "Professionalism", "Clarity"]]
            st.line_chart(score_trend)

            st.subheader("Escalation Handling (Pass/Fail)")
            st.bar_chart(df["Escalation Handling"].value_counts())

        elif dashboard_type == "Feedback Analytics":
            sheet = gc.open("Feedback_Analytics").sheet1
            records = sheet.get_all_records()
            df = pd.DataFrame(records)
            if df.empty:
                st.info("No feedback entries available.")
                return

            df["Timestamp"] = pd.to_datetime(df.get("Timestamp"), errors="coerce")
            df["Duration"] = pd.to_numeric(df.get("Duration"), errors="coerce")
            df["Rating"] = pd.to_numeric(df.get("Rating"), errors="coerce")

            #st.subheader("🕒 Time Spent on Feedback")
            plotly_bar_chart(df["Duration"], "Duration on Feedback")

            #st.subheader("🌟 Experience Ratings")
            plotly_bar_chart(df["Rating"], title="Experience Ratings")

            st.subheader("🧠 Task & Experience Feedback")
            for field in ["Task Clarity", "AI Quality", "Speed", "Usability", "Learning"]:
                if field in df.columns:
                    st.markdown(f"**{field}**")
                    st.bar_chart(df[field].value_counts())

            st.subheader("🎨 UI Experience Feedback")
            for field in ["Font Comfort", "Layout Clarity", "Navigation"]:
                if field in df.columns:
                    st.markdown(f"**{field}**")
                    st.bar_chart(df[field].value_counts())

            st.subheader("💬 Suggestions & Issues")
            st.dataframe(df[["Suggestions", "Issues", "Link"]].fillna(""), use_container_width=True)

    except Exception as e:
        st.error(f"Failed to load analytics: {e}")

# Feedback Page
def general_feedback():
    st.title("General Feedback")

    if "feedback_start_time" not in st.session_state:
        st.session_state.feedback_start_time = datetime.datetime.now()

    with st.form("general_feedback_form"):
        st.markdown("### Experience Feedback")

        rating = st.slider("How would you rate your overall experience?", 1, 5)

        clarity = st.radio("Was the task clear and easy to follow?", ["Yes", "No", "Somewhat"])
        ai_quality = st.radio("How would you rate the AI's responses?", ["Very Good", "Good", "Okay", "Poor", "Very Poor"])
        speed = st.radio("How did you find the response speed?", ["Fast", "Acceptable", "Slow"])
        usability = st.radio("Was the interface intuitive?", ["Yes", "No", "Somewhat"])
        learning = st.radio("Did you feel like you learned something useful?", ["Yes", "No", "Not Sure"])

        st.markdown("### UI Feedback")
        font_comfort = st.radio("Was the font size comfortable?", ["Yes", "No"])
        layout_clarity = st.radio("Was the layout easy to navigate?", ["Yes", "No"])
        accessibility = st.radio("Was it easy to find what you were looking for?", ["Yes", "No"])

        suggestions = st.text_area("Any suggestions or comments?", height=150, value="N/A")
        issues = st.text_area("Did you encounter any issues? If not, type N/A.", value="N/A")

        submitted = st.form_submit_button("Submit Feedback")

    if submitted:
        end_time = datetime.datetime.now()
        duration_seconds = int((end_time - st.session_state.feedback_start_time).total_seconds())

        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        filename = f"general_feedback_{timestamp.replace(':', '-')}.txt"
        file_path = os.path.join(os.getcwd(), filename)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("=== General Feedback Submitted ===\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"Time to complete: {duration_seconds} seconds\n")
            f.write(f"Experience Rating: {rating}/5\n")
            f.write(f"Task Clarity: {clarity}\n")
            f.write(f"AI Quality: {ai_quality}\n")
            f.write(f"Speed: {speed}\n")
            f.write(f"Usability: {usability}\n")
            f.write(f"Learning Value: {learning}\n")
            f.write(f"Font Comfort: {font_comfort}\n")
            f.write(f"Layout Clarity: {layout_clarity}\n")
            f.write(f"Ease of Navigation: {accessibility}\n")
            f.write(f"Suggestions: {suggestions}\n")
            f.write(f"Issues: {issues}\n")

        from google_utils import upload_to_drive, append_to_sheet

        if not st.session_state.testing_mode:
            drive_url = upload_to_drive(file_path, folder_id=FOLDER_CONVERSATIONS)
            append_to_sheet([
                timestamp,
                duration_seconds,
                rating,
                clarity,
                ai_quality,
                speed,
                usability,
                learning,
                font_comfort,
                layout_clarity,
                accessibility,
                suggestions,
                issues,
                drive_url
            ], sheet_name="Feedback_Analytics")
        
        st.success("Thank you! Your Feedback has been submitted.")

# Export Charts as PNG
def export_feedback_charts(df):
    import matplotlib.pyplot as plt
    import os

    export_dir = "/mnt/data/feedback_charts"
    os.makedirs(export_dir, exist_ok=True)
    saved_paths = []

    try:
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
        df["Rating"] = pd.to_numeric(df["Rating"], errors="coerce")

        # 1. Average Rating Over Time
        plt.figure()
        rating_trend = df.groupby(df["Timestamp"].dt.to_period("M"))["Rating"].mean()
        rating_trend.index = rating_trend.index.to_timestamp()
        plt.plot(rating_trend.index, rating_trend, marker="o")
        plt.title("Average Experience Rating Over Time")
        plt.ylabel("Rating")
        plt.xlabel("Month")
        rating_path = os.path.join(export_dir, "average_rating_over_time.png")
        plt.savefig(rating_path)
        saved_paths.append(rating_path)
        plt.close()

        # 2. AI Quality Distribution
        plt.figure()
        df["AI Quality"].value_counts().plot(kind="bar")
        plt.title("AI Response Quality Distribution")
        plt.ylabel("Responses")
        plt.xlabel("Quality")
        ai_path = os.path.join(export_dir, "ai_quality_distribution.png")
        plt.savefig(ai_path)
        saved_paths.append(ai_path)
        plt.close()

        # 3. Learning Value Pie Chart
        plt.figure()
        df["Learning"].value_counts().plot(kind="pie", autopct="%1.1f%%")
        plt.title("Learning Value")
        learning_path = os.path.join(export_dir, "learning_value.png")
        plt.savefig(learning_path)
        saved_paths.append(learning_path)
        plt.close()

        return saved_paths
    except Exception as e:
        st.error(f"Chart export failed: {e}")
        return []

# Main App Logic
def main():
    # Sidebar Navigation
    with st.sidebar:
        st.image("BurgerXpress_Logo.jpg", use_container_width=True)
        st.title("🍔 Navigation")

        st.markdown("### 🔠 Font Size")
        font_size = st.radio("Choose font size", ["Small", "Medium", "Large"], index=1)
        st.session_state.font_size = font_size

        font_scale = {"Small": "14px", "Medium": "18px", "Large": "22px"}[font_size]
        st.markdown(f"""
            <style>
            html, body, [data-testid="stAppViewContainer"] * {{
                font-size: {font_scale} !important;
            }}
            </style>
        """, unsafe_allow_html=True)

        options = [
            "Main Menu", "Instructions", "Start Conversation", "Show Menu",
            "Service Guidelines", "Past Conversations", "General Feedback", "Analytics" 
        ]
        st.markdown("### Navigation")
        for page in options:
            if st.button(page, use_container_width=True):
                st.session_state.page = page
                st.rerun()

        st.markdown("---")
        st.session_state.role = st.radio("Select Role", ["Crew", "Manager"], index=0)

        st.markdown("---")
        st.markdown("### Developer Access")
        pwd = st.text_input("Enter Developer Password", type="password")
        if pwd == "test123":
            st.session_state.testing_mode = True
            st.success("Testing Mode Enabled")
        else:
            st.session_state.testing_mode = False

    # Page Routing
    if st.session_state.page == "Main Menu":
        main_menu()
    elif st.session_state.page == "Start Conversation":
        start_conversation()
    elif st.session_state.page == "Show Menu":
        show_menu()
    elif st.session_state.page == "Service Guidelines":
        service_guidelines()
    elif st.session_state.page == "Instructions":
        instructions()
    elif st.session_state.page == "Past Conversations":
        past_conversations()
    elif st.session_state.page == "General Feedback":
        general_feedback()
    elif st.session_state.page == "Analytics":
        analytics_dashboard()

# Run the Streamlit app
if __name__ == "__main__":
    main()