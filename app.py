"""Phone Advisor — a local chat assistant that recommends phones from a database.

The UI. The phone search lives in recommender.py and the model call in bot.py.
Everything runs on your machine. Start it with:

    streamlit run app.py
"""

import streamlit as st

import bot
import recommender

MAX_INPUT = 500  # characters accepted per message

EXAMPLES = [
    "Arzon telefon, batareyasi katta",
    "Best camera phone under $500",
    "Something for my mum who loves photos",
    "Samsung yoki Xiaomi, $300 atrofida",
]

CARD_CSS = """
<style>
  #MainMenu, footer {visibility: hidden;}
  .block-container {max-width: 880px; padding-top: 2.2rem;}
  [data-testid="stChatMessage"] {padding: 0.2rem 0;}
  .pgrid {display: flex; flex-wrap: wrap; gap: 10px; margin: 6px 0;}
  .pcard {flex: 1 1 230px; max-width: 270px; background: #171c28;
          border: 1px solid #273043; border-radius: 12px; padding: 12px 14px;}
  .pcard .top {display: flex; justify-content: space-between; align-items: baseline;}
  .pcard .brand {color: #8aa0c0; font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;}
  .pcard .price {color: #3b82f6; font-weight: 700; font-size: 1.05rem;}
  .pcard .name {font-weight: 600; margin: 2px 0 9px; font-size: .95rem;}
  .pcard .chips {display: flex; flex-wrap: wrap; gap: 6px;}
  .pcard .chips span {background: #0e1117; border: 1px solid #273043; border-radius: 999px;
                      padding: 2px 9px; font-size: .72rem; color: #c7d0e0;}
</style>
"""


def cards(rows, n=6):
    def one(r):
        chips = "".join(f"<span>{c}</span>" for c in (
            f"{r['ram_gb']}GB RAM", f"{r['storage_gb']}GB", f"{r['battery_mah']}mAh",
            f'{r["screen_in"]}"', f"{r['camera_main_mp']}MP",
        ))
        return (f'<div class="pcard"><div class="top">'
                f'<span class="brand">{r["brand"]}</span>'
                f'<span class="price">${r["price_usd"]}</span></div>'
                f'<div class="name">{r["model"]}</div>'
                f'<div class="chips">{chips}</div></div>')
    st.markdown(f'<div class="pgrid">{"".join(one(r) for r in rows[:n])}</div>',
                unsafe_allow_html=True)


@st.cache_resource
def get_conn():
    # One read-only connection shared across reruns (no leaks, can't modify data).
    return recommender.connect(read_only=True)


st.set_page_config(page_title="Phone Advisor", page_icon="📱", layout="centered")
st.markdown(CARD_CSS, unsafe_allow_html=True)

try:
    conn = get_conn()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

with st.sidebar:
    st.header("📱 Phone Advisor")
    st.write("Ask for a phone by **budget**, **brand**, or what matters most — "
             "battery, camera, gaming. English yoki o'zbekcha.")
    st.caption(f"Model: `{bot.MODEL}`")
    st.divider()
    st.write("**Try one:**")
    for ex in EXAMPLES:
        if st.button(ex, use_container_width=True):
            st.session_state.pending = ex

st.title("📱 Phone Advisor")
st.caption("Tell me your budget and what matters to you — I'll suggest a phone. "
           "Budjet va talabingizni yozing, men telefon tavsiya qilaman.")

if "messages" not in st.session_state:
    st.session_state.messages = []

if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown("Hi! What are you looking for in a phone? "
                    "Salom! Qanaqa telefon qidiryapsiz? 📱")
    st.markdown("###### ✨ Popular picks")
    cards(recommender.diverse_sample(conn, 6))

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

typed = st.chat_input("e.g. cheap phone with a big battery / arzon, batareyasi katta", max_chars=MAX_INPUT)
prompt = st.session_state.pop("pending", None) or typed

if prompt:
    prompt = prompt.strip()
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    rows = recommender.candidates(conn, prompt)
    with st.chat_message("assistant"):
        try:
            reply = st.write_stream(bot.reply(st.session_state.messages, rows))
        except bot.ModelError as e:
            reply = str(e)
            st.error(reply)
        except Exception:  # never show a raw traceback to the user
            reply = "Something went wrong handling that. Please try again."
            st.error(reply)

        with st.expander(f"🔎 Grounded on these {len(rows)} phones"):
            cards(rows, n=8)

    st.session_state.messages.append({"role": "assistant", "content": reply})
