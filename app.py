"""
app.py

Gradio interface for FitFindr. handle_query() calls run_agent() and maps
the session results to the output panels, including the stretch-feature
panels (price check, trending styles) and the retry-ladder adjustment note.

Run with:
    python app.py

Then open the localhost URL shown in your terminal (usually http://localhost:7860,
but check your terminal — the port may differ).
"""

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe
from style_memory import save_style_profile, load_style_profile

SAVED_PROFILE_LABEL = "Saved profile (remembered)"


# -- query handler -----------------------------------------------------------------

def handle_query(user_query: str, wardrobe_choice: str) -> tuple[str, str, str, str, str]:
    """
    Called by Gradio when the user submits a query.

    Args:
        user_query:      The text the user typed into the search box.
        wardrobe_choice: "Example wardrobe", "Empty wardrobe (new user)",
                         or "Saved profile (remembered)" (Style Profile
                         Memory stretch feature).

    Returns:
        A tuple of five strings:
            (listing_text, outfit_suggestion, fit_card, price_text, trend_text)
    """
    if not user_query or not user_query.strip():
        return "Please enter a query describing what you're looking for.", "", "", "", ""

    if wardrobe_choice == SAVED_PROFILE_LABEL:
        wardrobe = load_style_profile()
        if wardrobe is None:
            return (
                "No saved style profile yet -- run a query with \"Example wardrobe\" "
                "selected first, and it'll be remembered for next time.",
                "", "", "", "",
            )
    elif wardrobe_choice == "Example wardrobe":
        wardrobe = get_example_wardrobe()
        save_style_profile(wardrobe)  # remember it for a later "Saved profile" run
    else:
        wardrobe = get_empty_wardrobe()

    session = run_agent(query=user_query, wardrobe=wardrobe)

    if session["error"]:
        return session["error"], "", "", "", ""

    item = session["selected_item"]
    adjustment_note = ""
    if session["adjustments"]:
        adjustment_note = (
            f"(Note: no exact match for your filters -- showing results after "
            f"{' and '.join(session['adjustments'])}.)\n\n"
        )
    listing_text = (
        f"{adjustment_note}"
        f"{item['title']}\n"
        f"${item['price']:.2f} on {item['platform']} -- {item['condition']} condition\n"
        f"Size: {item['size']}\n\n"
        f"{item['description']}"
    )

    trend_text = "No trend data matched this size."
    if session["trending_styles"]:
        trend_text = "\n".join(
            f"#{t['style_tag']} (score {t['trend_score']:.2f}) -- {t['note']}"
            for t in session["trending_styles"]
        )

    return (
        listing_text,
        session["outfit_suggestion"],
        session["fit_card"],
        session["price_assessment"],
        trend_text,
    )


# -- interface ------------------------------------------------------------------

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "chunky white sneakers under $60",
    "vintage graphic tee under $30, size XL",  # retry-with-fallback demo
    "designer ballgown size XXS under $5",           # deliberate no-results test
]

def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            wardrobe_choice = gr.Radio(
                choices=[
                    "Example wardrobe",
                    "Empty wardrobe (new user)",
                    SAVED_PROFILE_LABEL,
                ],
                value="Example wardrobe",
                label="Wardrobe",
                scale=1,
            )

        submit_btn = gr.Button("Find it", variant="primary")

        with gr.Row():
            listing_output = gr.Textbox(
                label="🛍️ Top listing found",
                lines=8,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=8,
                interactive=False,
            )
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=8,
                interactive=False,
            )

        with gr.Row():
            price_output = gr.Textbox(
                label="💰 Price check",
                lines=4,
                interactive=False,
            )
            trend_output = gr.Textbox(
                label="📈 Trending now",
                lines=4,
                interactive=False,
            )

        gr.Examples(
            examples=[[q, "Example wardrobe"] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice],
            label="Try these queries",
        )

        outputs = [listing_output, outfit_output, fitcard_output, price_output, trend_output]

        submit_btn.click(fn=handle_query, inputs=[query_input, wardrobe_choice], outputs=outputs)
        query_input.submit(fn=handle_query, inputs=[query_input, wardrobe_choice], outputs=outputs)

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()
