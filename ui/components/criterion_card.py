"""Reusable Streamlit component: criterion card with source annotations."""

import streamlit as st


def render_criterion_card(criterion: dict, project_id: str, api_base: str) -> None:
    import httpx

    ctype = criterion.get("criterion_type", "inclusion")
    is_gold = criterion.get("is_gold", False)
    gold_tag = " 🔒" if is_gold else ""
    icon = "✅" if ctype == "inclusion" else "❌"
    label = f"{icon} **{ctype.upper()}**{gold_tag}"

    with st.expander(f"{label}: {criterion['statement'][:80]}...", expanded=False):
        st.markdown(f"**Statement:** {criterion['statement']}")
        st.markdown(f"**Rationale:** {criterion.get('rationale', '')}")

        sources = criterion.get("source_ids", [])
        if sources:
            st.markdown("**Sources:** " + " · ".join(f"`{s}`" for s in sources))

        confidence = criterion.get("confidence")
        if confidence:
            st.progress(confidence, text=f"Confidence: {confidence:.0%}")

        if is_gold and criterion.get("gold_note"):
            st.info(f"**Analyst note:** {criterion['gold_note']}")

        # Toggle Gold Value
        new_gold = st.checkbox(
            "Mark as Gold Value (hard constraint)",
            value=is_gold,
            key=f"gold_{criterion['id']}",
        )
        if new_gold != is_gold:
            note = st.text_input("Analyst note (optional)", key=f"note_{criterion['id']}")
            if st.button("Save", key=f"save_{criterion['id']}"):
                try:
                    httpx.patch(
                        f"{api_base}/projects/{project_id}/criteria/{criterion['id']}",
                        json={"is_gold": new_gold, "gold_note": note or None},
                        timeout=10,
                    )
                    st.success("Saved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save: {e}")
