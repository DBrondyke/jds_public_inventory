import os
from typing import Optional

import pandas as pd
import psycopg
from psycopg.rows import dict_row
import streamlit as st

st.set_page_config(page_title="Inventory | JD's Hobby Shop", page_icon="https://www.jdshobbyshop.com/uploads/b/2013d3a0-5469-11f0-ab67-efb86e797f87/Untitled%20(64%20x%2064%20px).jpg", layout="wide")


def get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url
    return st.secrets["database"]["url"]


def get_connection():
    return psycopg.connect(
        get_database_url(),
        row_factory=dict_row,
    )


def search_public_inventory(
    *,
    name_query: str,
    set_query: str,
    max_price: Optional[float],
    in_stock_only: bool,
) -> pd.DataFrame:
    sql = """
    WITH grouped_inventory AS (
        SELECT
            MIN(cp.card_name) AS card_name,
            MIN(cp.set_name) AS set_name,
            cp.set_code,
            cp.collector_number,
            MIN(cp.mana_cost) AS mana_cost,
            MIN(cp.color_identity) AS color_identity,
            MIN(cp.type_line) AS type_line,
            MIN(cp.oracle_text) AS oracle_text,
            SUM(si.stock) AS total_stock,
            MIN(si.effective_price) AS price
        FROM shop_inventory si
        JOIN card_printings cp
          ON cp.scryfall_id = si.scryfall_id
        WHERE si.is_active = TRUE
    """
    params = []

    if in_stock_only:
        sql += " AND si.stock > 0"

    if name_query.strip():
        sql += " AND cp.card_name ILIKE %s"
        params.append(f"%{name_query.strip()}%")

    if set_query.strip():
        sql += " AND (cp.set_name ILIKE %s OR LOWER(cp.set_code) = %s)"
        params.append(f"%{set_query.strip()}%")
        params.append(set_query.strip().lower())

    if max_price is not None:
        sql += " AND si.effective_price <= %s"
        params.append(max_price)

    sql += """
        GROUP BY
            cp.set_code,
            cp.collector_number
    )
    SELECT
        card_name,
        set_name,
        set_code,
        collector_number,
        mana_cost,
        color_identity,
        type_line,
        oracle_text,
        total_stock,
        price
    FROM grouped_inventory
    ORDER BY
        card_name,
        set_name,
        CASE
            WHEN collector_number ~ '^[0-9]+$' THEN CAST(collector_number AS INTEGER)
            ELSE 999999
        END,
        collector_number
    """

    with get_connection() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    columns = [
        "card_name",
        "set_name",
        "set_code",
        "collector_number",
        "mana_cost",
        "color_identity",
        "type_line",
        "oracle_text",
        "total_stock",
        "price",
    ]

    if not rows:
        return pd.DataFrame(columns=columns)

    return pd.DataFrame([dict(r) for r in rows], columns=columns)

# inventory table helpers

def get_table_key() -> str:
    if "inventory_table_version" not in st.session_state:
        st.session_state["inventory_table_version"] = 0
    return f"inventory_table_{st.session_state['inventory_table_version']}"

def clear_table_selection():
    st.session_state["inventory_table_version"] += 1

def render_inventory_table(df: pd.DataFrame):
    return st.dataframe(
        df,
        key=get_table_key(),
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_order=[
            "card_name",
            "set_name",
            "mana_cost",
            "color_identity",
            "type_line",
            "price",
            "availability",
            "set_code",
            "collector_number",
        ],
        column_config={
            "card_name": st.column_config.TextColumn("Card Name", width="medium"),
            "set_name": st.column_config.TextColumn("Set", width="medium"),
            "mana_cost": st.column_config.TextColumn("Cost", width="small"),
            "color_identity": st.column_config.TextColumn("Color", width="small"),
            "type_line": st.column_config.TextColumn("Type", width="medium"),
            "price": st.column_config.NumberColumn("Price", format="$%.2f"),
            "availability": st.column_config.TextColumn("Availability", width="small"),
            "set_code": st.column_config.TextColumn("Set Code", width="small"),
            "collector_number": st.column_config.TextColumn("Collector #", width="small"),
        },
    )

def get_selected_rows() -> list[int]:
    table_state = st.session_state.get(get_table_key(), {})
    selection = table_state.get("selection", {})
    rows = selection.get("rows", [])
    return rows if isinstance(rows, list) else []

def clean_text(value, fallback="-"):
    if value is None:
        return fallback
    text = str(value).strip()
    if text == "" or text.lower() == "none" or text.lower() == "nan":
        return fallback
    return text

def format_in_stock(total_stock) -> str:
    try:
        return "In Stock" if int(total_stock) > 0 else "Out of Stock"
    except Exception:
        return "Out of Stock"

st.title("JD's Hobby Shop")
st.caption("Browse current singles in stock")

with st.sidebar:
    col1, col2 = st.columns([1, 1])

    with col1:
        st.image("https://3464afe7d7c20f433c55.cdn6.editmysite.com/uploads/b/3464afe7d7c20f433c5554417c99be366c21051c92abce030a6e8e9980742b5e/Untitled%20design_1751320691.png?width=2400&optimize=medium", width=90)

    with col2:
        st.write("")
        st.write("")
        st.link_button("Visit homepage", "https://www.jdshobbyshop.com/", width="content")
    st.header("Filters")
    name_query = st.text_input("Card name")
    set_query = st.text_input("Set name or code")
    max_price_enabled = st.checkbox("Set max price")
    max_price = None
    if max_price_enabled:
        max_price = st.number_input("Max price", min_value=0.0, step=1.0, format="%.2f")
    in_stock_only = st.checkbox("Only show cards in stock", value=True)

results_df = search_public_inventory(
    name_query=name_query,
    set_query=set_query,
    max_price=max_price,
    in_stock_only=in_stock_only,
)

if results_df.empty:
    st.write("Select a card to view details.")
    st.write(f"Matches: {len(results_df)}")
    st.info("No cards match current filters.")
else:
    display_df = results_df[
        [
            "card_name",
            "set_name",
            "mana_cost",
            "color_identity",
            "type_line",
            "price",
            "total_stock",
            "set_code",
            "collector_number",
        ]
    ].copy()
    
    display_df["mana_cost_display"] = display_df["mana_cost"].apply(lambda v: clean_text(v, "-"))
    display_df["color_identity_display"] = display_df["color_identity"].apply(lambda v: clean_text(v, "-"))
    selected_rows = get_selected_rows()
    
    # Guard against stale selection after filters change
    if selected_rows and selected_rows[0] >= len(results_df):
        selected_rows = []
    
    # Put above match count
    if not selected_rows:
        st.write("Select a card to view details.")
        st.write(f"Matches: {len(results_df)}")
        render_inventory_table(display_df)
    else:
        st.write(f"Matches: {len(results_df)}")
        
        left, right = st.columns([3, 2])

        with left:
            render_inventory_table(display_df)

        with right:
            selected_row = results_df.iloc[selected_rows[0]]
            
            c1, c2 = st.columns([3,1], vertical_alignment="bottom")
            with c1:
                st.subheader(selected_row["card_name"])
            with c2:
                st.button("Clear selection", on_click=clear_table_selection, width="content")
            st.write(f"**Set:** {selected_row['set_name']} ({selected_row['set_code']})")
            st.write(f"**Collector #:** {selected_row['collector_number']}")
            st.write(f"**Cost:** {clean_text(selected_row['mana_cost'],'-')}")
            st.write(f"**Color:** {clean_text(selected_row['color_identity'],'Colorless')}")
            st.write(f"**Type:** {selected_row['type_line'] or '-'}")
            st.write(f"**Availability:** {format_in_stock(selected_row['total_stock'])}")
            st.write(f"**Price:** ${float(selected_row['price']):.2f}" if selected_row["price"] is not None else "**Price:** -")

            st.text_area(
                "Oracle Text",
                value=selected_row["oracle_text"] or "",
                height=220,
                disabled=True,
            )

st.caption("Public inventory viewer")
