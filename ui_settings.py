"""The ⚙️ Settings page: choose the AI service, add up to 5 API keys, test and save them."""
from __future__ import annotations

import streamlit as st

from agent import keycheck, keystore
from agent.llm import FailoverLLM

STATE_ICON = {"in use": "🟢", "ready": "⚪", "resting": "🟠", "rejected": "🔴"}


def _apply(bundle) -> None:
    """Make the running agent use what is saved (keeps your chat, PDF and memory)."""
    keystore.apply_saved(bundle.settings)
    if not bundle.settings.fake_llm:
        bundle.agent.llm = FailoverLLM(bundle.settings)


def render_settings(bundle) -> None:
    settings = bundle.settings
    saved = keystore.load_saved(settings.data_dir)
    gen = st.session_state.setdefault("settings_gen", 0)
    tests = st.session_state.setdefault("key_tests", {})

    st.title("⚙️ Settings")
    if settings.fake_llm:
        st.warning("Demo mode is on, so these settings are saved but not used until you start the "
                   "app without STUDY_AGENT_FAKE.")
    if not settings.all_keys() and not settings.fake_llm:
        st.info("No API key yet. Paste one below, press **Test**, then **Save settings**.")
    if st.session_state.pop("settings_saved", False):
        st.success("Saved. The agent is now using these settings.")

    # ---------------- provider and model ----------------
    st.subheader("1. Which AI service?")
    current_preset = saved["preset"] or keystore.preset_for(settings.base_url)
    names = list(keystore.PRESETS)
    if current_preset not in names:
        current_preset = names[-1]

    def on_preset_change():
        p = keystore.PRESETS.get(st.session_state[f"preset_{gen}"], {})
        if p:
            st.session_state[f"base_url_{gen}"] = p["base_url"]
            st.session_state[f"model_{gen}"] = p["model"]

    st.session_state.setdefault(f"base_url_{gen}", settings.base_url)
    st.session_state.setdefault(f"model_{gen}", settings.model)
    preset = st.selectbox("Service", names, index=names.index(current_preset),
                          key=f"preset_{gen}", on_change=on_preset_change)
    c1, c2 = st.columns(2)
    base_url = c1.text_input("Address (base URL)", key=f"base_url_{gen}")
    model = c2.text_input("Model name", key=f"model_{gen}")
    st.caption("Groq + `openai/gpt-oss-120b` (or `openai/gpt-oss-20b`) is the default. "
               "Keys from console.groq.com start with `gsk_`. Keys from xAI's console only work with the xAI Grok option.")

    # ---------------- keys ----------------
    st.subheader("2. API keys (up to 5)")
    st.caption("The agent starts with Key 1. If a key hits its limit, runs out of credits or is rejected, "
               "it switches to the next one by itself, and comes back to a resting key when it recovers. "
               "Keys are saved only on this computer (`data/settings.json`, never uploaded to GitHub).")

    typed: list[str] = []
    labels: list[str] = []
    for i in range(keystore.MAX_KEYS):
        slot = saved["keys"][i]
        with st.container(border=True):
            top = st.columns([1, 3])
            labels.append(top[0].text_input("Name", value=slot["label"], key=f"label_{i}_{gen}",
                                            label_visibility="collapsed"))
            ph = f"saved: {keystore.mask(slot['key'])}  (leave empty to keep)" if slot["key"] else "Paste key here"
            typed.append(top[1].text_input("API key", type="password", placeholder=ph, key=f"key_{i}_{gen}",
                                           label_visibility="collapsed"))
            b1, b2, _ = st.columns([1, 1, 4])
            if b1.button("🔍 Test", key=f"test_{i}_{gen}"):
                key = typed[i].strip() or slot["key"]
                with st.spinner("Testing..."):
                    tests[i] = keycheck.check_key(settings, key, base_url, model)
            if slot["key"] and b2.button("🗑 Remove", key=f"rm_{i}_{gen}"):
                keys = [dict(s) for s in saved["keys"]]
                keys[i]["key"] = ""
                keystore.save(settings.data_dir, preset, base_url, model, keys)
                _apply(bundle)
                tests.pop(i, None)
                st.session_state.settings_gen = gen + 1
                st.session_state.settings_saved = True
                st.rerun()
            if i in tests:
                status, msg = tests[i]
                {"ok": st.success, "limited": st.warning, "bad": st.error}[status](msg)

    # ---------------- save ----------------
    if st.button("💾 Save settings", type="primary"):
        keys = []
        for i in range(keystore.MAX_KEYS):
            keys.append({"label": labels[i], "key": typed[i].strip() or saved["keys"][i]["key"]})
        keystore.save(settings.data_dir, preset, base_url, model, keys)
        _apply(bundle)
        st.session_state.settings_gen = gen + 1   # clears the typed boxes
        st.session_state.settings_saved = True
        st.session_state.key_tests = {}
        st.rerun()

    # ---------------- live status ----------------
    llm = bundle.agent.llm
    if isinstance(llm, FailoverLLM) and llm.has_keys:
        st.subheader("3. Live status")
        for row in llm.statuses():
            extra = f" - {row['detail']}" if row["detail"] else ""
            st.write(f"{STATE_ICON[row['state']]} **{row['label']}**: {row['state']}{extra} "
                     f"· {row['tokens']:,} tokens used this session")

    # ---------------- models ----------------
    with st.expander("Show models my key can use"):
        usable = typed[0].strip() or next((k for _, k in settings.all_keys()), "")
        if st.button("List models"):
            with st.spinner("Asking the service..."):
                found = keycheck.list_models(settings, usable, base_url)
            st.write(found if found else "Couldn't get a list. Check the key and address first.")
