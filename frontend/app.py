import streamlit as st 
import requests 
import time
from datetime import datetime

# Streamlit app configuration
st.set_page_config(
    page_title="NutriGuide AI",
    page_icon=":streamlit:",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS and Styling
st.markdown("""
<style>
    /* Main Container */
  st.App{
    max-width: 1200px;
    margin: 0 auto;
    font-family: 'SN pro', sans-serif;
  }


   /* Safety Disclaimer */
    .disclaimer-box {
    background-color: #fff3cd;
    border: 1px solid #97993A;
    padding: 15px;
    margin: 20px 0;
    font-size: 14px;
    line-height: 1.5;
    color: #333333;
    }

   /* Source citation badges */
    .source-badge {
    display: inline-block;
    background-color : #9E9E9D;
    padding 3px 8px ;
    border-radius: 12px;
    font-size: 12px;
    margin-right : 5px ; 
    margin-bottom: 5px;
    border: 1px solide #dee2e6;
    }


   /* Blocked medical query styling */
    .blocked-query{
        background-color: #f8d7da;          /* Light red for warnings */
        border: 1px solid #f5c6cb;          /* Red border */
        border-radius: 8px;
        padding: 15px;
        margin: 20px 0;
        line-height: 1.6;
    }


   /* Response box styling */
    .response-box{
        background-color: #f8f9fa;          /* Light gray background */
        border-left: 4px solid #28a745;     /* Green left border */
        padding: 15px;
        border-radius: 0 8px 8px 0;
        margin: 15px 0;
        line-height: 1.6;
    }


   /* Footer styling */
    .footer {
        text-align: center;
        padding: 20px;
        color: #6c757d;
        font-size: 13px;
        border-top: 1px solid #e9ecef;
        margin-top: 30px;
    }
<style>""", unsafe_allow_html=True)

# Header & Safety Disclaimer

col1,col2 = st.columns([1,6]) #col1 for logo col2 for title

with col1:
    st.image("frontend/assets/logo.png", width=80)

with col2:
    st.title("NutriGuide AI")
    st.caption("Verified Nutrition Information at Your Fingertips")

# CRITICAL SAFETY DISCLAIMER (always visible on top)
st.markdown("""

<div class="disclaimer-box">
<strong>Safety Disclaimer:</strong> NutriGuide AI provides information based on a curated dataset of nutrition sources. It is not a substitute for professional medical advice, diagnosis, or treatment. Always consult with a qualified healthcare provider for any medical concerns or before making significant changes to your diet or health regimen.
</div>
""", unsafe_allow_html=True)

# Chat history management 
if "messages" not in st.session_state:
    st.session_state.messages =[] #(list to hold messages)

# Display existing chat messages 
for message in st.session_state.messages:
    #creating chat message bubble with role (user and message)
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        #show source of citation if available 
        if "sources" in message and message["sources"]:
            #create source badge of top 3 sources
            source_badges = " ".join([
                f"<span class='source-badge'>{src['source_id'].replace('_', ' ').title()} (p.{src['page']})</span>" 
                for src in message["sources"][:3] #show top 3 sources
            ])
            st.markdown(f"<div style='margin-top: 10px;'>{source_badges}</div>", unsafe_allow_html=True)

        #Display of special not of disclaimer
        if message.get("safety_level") == "medical_caution":
            st.info("ℹ️ This response contains medical information. Always consult a healthcare professional for personalized advice.")

# Chat input and API integration 
# Create chat input box with placeholder text
if prompt := st.chat_input("Ask NutriGuide AI about nutrition, diets, or health-related topics..."):
    # Validate prompt before sending to API 
    if not prompt or len(prompt.strip())<3:
        st.warning("Please Enter a valid question with at least 3 characters.")
    else:
        clean_prompt = prompt.strip() #remove leading/trailing whitespace
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})

    #Display user message in chat interface
    with st.chat_message("user"):
        st.markdown(prompt)
        
    #Create assistant message when thinking
    with st.chat_message("assistant"):
        message_placeholder = st.empty() #placeholder for streaming assistant response
        message_placeholder.markdown("thinking... :hourglass_flowing_sand:")

        #Call API with error handling 
        try:
            start_time = time.time() #start timer (bug fix: changed start to start_time to avoid conflict with start function)
            response = requests.post(
                "http://localhost:8000/query", # Fastapi endpoint 
                json={"question": prompt},     # send question as json
                timeout=30                     # 30 seconds timeout     
            )
            response_time = time.time() - start_time
            #Handle successful api response http 200
            if response.status_code == 200:
                result = response.json()

                #Handle blocked medical queries
                if result["safety_level"] == "blocked":
                    blocked_message = """
                    <div class="blocked-query">
                    <strong>⚕️ Medical Advice Required</strong><br><br>
                    This question requires personnalized medical expertise. I cannot provide a response. Please consult a healthcare professional for accurate information and guidance.
                    <br><br>
                    <strong>Please Consult:</strong>
                    <ul> <li>Registered Dietitians</li> <li>Licensed Nutritionists</li> <li>Medical Doctors specializing in nutrition</li> </ul>
                    <br><br>
                    I can answer general questions about USDA/WHO nutrition guidelines 
                    that don't involve your personal health conditions.
                    </div>
                    """
                    message_placeholder.markdown(blocked_message, unsafe_allow_html=True)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": "Medical advice query blocked - requires professional consultation.",
                        "safety_level": "blocked"
                    })

                    # Handling Normal responses
                else:
                        # Format response with metadata footer
                        response_text = result["response"]

                        # Add metadata footer and source count 
                        response_text += f"\n\n<sub> Response generated in {response_time:.1f} seconds using {len(result['sources'])} sources. </sub>"

                        # display response in chat interface
                        message_placeholder.markdown(response_text, unsafe_allow_html=True)
                        # Add chat history with metadata 
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": result["response"],
                            "sources": result["sources"],
                            "safety_level": result["safety_level"]
                        })
                # Handle blocked queries at API layer (HTTP 403)
            elif response.status_code == 403:
                    blocked_message = """
                    <div class="blocked-query">
                    <strong>⚕️ Medical Advice Required</strong><br><br>
                    For safety reasons, I cannot answer questions that require personalized medical advice. Please consult a healthcare professional for accurate information and guidance.
                    <br><br>
                    </div>
                    """
                    placeholder.markdown(blocked_message, unsafe_allow_html=True)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": "Medical advice query blocked - requires professional consultation.",
                        "safety_level": "blocked"
                    })

            # Handle validation errors (HTTP 422) from pydantic 
            elif response.status_code == 422:
                try:
                    error_details = response.json().get("detail", [{"msg": "Invalid question format."}])[0].get("msg", "Invalid question format.")
                    if isinstance(error_detail, list):
                        error_message = error_details[0].get("msg", "Question validation failed.")
                    else:
                        error_message = str(error_details)
                except:
                    error_message = "Question must be 3-500 characters with valid format. Please revise and try again."

                error_message = f"⚠️ {error_msg}"
                message_placeholder.error(error_message)
                st.session_state.messages.append({
                "role": "assistant", 
                "content": error_message
                })



            # Handle other API errors
            else: 
                error_message = f"❌ Error: Received status code {response.status_code} from API. Please try again later."
                message_placeholder.error(error_message)
                st.session_state.messages.append({
                        "role": "assistant",
                        "content": error_message
                    })

        # Handle network errors
        except requests.exceptions.ConnectionError:
                    error_message = "❌ Network error: Unable to connect to the nutrition database. Please check your connection and try again."
                    message_placeholder.error(error_message)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": error_message
                    })

        # Handle timeouts errors
        except requests.exceptions.Timeout:
                error_message = "⚠️ Request timed out. The nutrition database may be busy. Please try again."
                message_placeholder.error(error_message)
                st.session_state.messages.append({

                })

        # Handle unexpected errors
        except Exception as e:
                error_message = f"⚠️ An unexpected error occurred: {str(e)}"
                message_placeholder.error(error_message)
                st.session_state.messages.append({
                        "role": "assistant",
                        "content": error_message
                })
                
# SIDEBAR WITH ADDITIONAL INFO
#Creating Sidebar with safety information and examples
with st.sidebar:
    st.header("About NutriGuide AI")
    st.markdown(""" \n \n

    **Verified Sources:** \n
    - Dietary Guidelines for Americans (USDA/HHS)
    - World Health Organization (WHO) guidelines
    - Evidence-based recommendations only
    
    **Safety Features:** \n
    - ✅ Medical advice queries automatically blocked
    - ✅ Every fact includes source citations
    - ✅ Mandatory disclaimers on all responses
    - ✅ Audit trail for compliance
    
    **System Limitations:** \n
    - ❌ Not a substitute for medical advice
    - ❌ Cannot diagnose conditions
    - ❌ Cannot recommend supplements/dosages
    - ❌ Cannot provide personalized meal plans

    """)

    st.markdown("---")
    st.subheader("Example Questions to Ask NutriGuide AI :  ")

    # Provide example questions to guide users
    st.markdown("""

    ✅ "What is the daily sodium limit for adults?" \n
    ✅ "How much added sugar should children consume?" \n
    ✅ "What are good sources of potassium?"    \n
    ✅ "Vitamin D recommendations during pregnancy?" \n

    """)

   # Bad examples of questions that would be blocked
    st.subheader("Example Questions NOT to Ask NutriGuide AI :")
    st.markdown("""

    ❌ "Should I take vitamin D supplements?" \n
    ❌ "What foods should I avoid with diabetes?" \n
    ❌ "How many mg of zinc should I take daily?" \n
    ❌ "Can you diagnose my nutritional deficiency?" \n
    """)
    st.markdown("---")
    st.caption(f"NutriGuide v1.0 {datetime.now().year} Safety-First Nutrition Chatbot")


# Footer 
st.markdown("""

<div  class="footer">
    <p>© 2026 NutriGuide. All nutrition information sourced from USDA and WHO public domain documents. 
    This service complies with FDA guidance on health information systems.</p>
    <p><strong>Emergency Notice:</strong> If you are experiencing a medical emergency, call emergency services immediately. 
    Do not rely on this service for urgent medical needs.</p>
""", unsafe_allow_html=True)

