import dash
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
import pandas as pd
from sqlalchemy import create_engine, text

dash.register_page(__name__, path='/workspaces')

POSTGRES_URI = "postgresql://admin:secret_password@localhost:5432/energy_lake"
engine = create_engine(POSTGRES_URI)

try:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()
except Exception as e:
    print(f"Ошибка инициализации таблицы областей: {e}")

layout = dbc.Container([
    dcc.Location(id='url-workspaces-list', refresh=True),

    dbc.Row([
        dbc.Col(html.H2("Коллекции и воркбуки", className="mb-4 fw-bold text-dark"), width=8)
    ], className="mt-4"),

    dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col(dbc.Input(id="new-workspace-name", placeholder="Введите название новой рабочей области...",
                                  type="text"), width=9),
                dbc.Col(dbc.Button("Создать область", id="btn-create-workspace", color="primary", className="w-100"),
                        width=3)
            ]),
            html.Div(id="create-ws-status", className="mt-2 text-danger fw-bold")
        ])
    ], className="mb-4 shadow-sm"),

    # Оптимизированный поиск с debounce
    dbc.Input(id="search-workspaces", placeholder="Искать рабочие области по названию (нажмите Enter для поиска)...",
              className="mb-4 shadow-sm", type="text", debounce=True),

    html.Div(id='workspaces-grid', className="mt-4")
], fluid=True, className="px-4")


@callback(
    Output('workspaces-grid', 'children'),
    Output('create-ws-status', 'children'),
    Output('new-workspace-name', 'value'),
    Input('auth-state', 'data'),
    Input('btn-create-workspace', 'n_clicks'),
    Input('search-workspaces', 'value'),
    State('new-workspace-name', 'value')
)
def render_workspaces(auth_state, n_clicks, search_text, new_name):
    if not auth_state or not auth_state.get('logged_in'):
        return html.Div("Загрузка сессии...", className="text-muted text-center mt-5"), "", dash.no_update

    user_id = auth_state['user_id']
    status_msg = ""
    clear_input = dash.no_update

    ctx = dash.callback_context
    triggered = ctx.triggered[0]['prop_id'] if ctx.triggered else ""

    try:
        with engine.connect() as conn:
            if 'btn-create-workspace' in triggered:
                if new_name:
                    conn.execute(text("INSERT INTO workspaces (user_id, name) VALUES (:u, :n)"),
                                 {"u": user_id, "n": new_name})
                    conn.commit()
                    status_msg = ""
                    clear_input = ""
                else:
                    status_msg = "Укажите название рабочей области"

            df = pd.read_sql(
                text("SELECT id, name, created_at FROM workspaces WHERE user_id = :uid ORDER BY created_at DESC"),
                conn, params={"uid": user_id}
            )

            if not df.empty and search_text and str(search_text).strip():
                df = df[df['name'].str.contains(search_text, case=False, na=False, regex=False)]

            if df.empty:
                return html.Div("Рабочие области не найдены.",
                                className="text-muted text-center mt-5 fs-5"), status_msg, clear_input

            table_rows = []
            for _, row in df.iterrows():
                link_url = f"/workspace-view?ws_id={row['id']}"
                table_rows.append(html.Tr([
                    html.Td(html.A(row['name'], href=link_url,
                                   style={'textDecoration': 'none', 'display': 'block', 'fontWeight': 'bold'})),
                    html.Td(html.A(pd.to_datetime(row['created_at']).strftime('%d.%m.%Y %H:%M'), href=link_url,
                                   style={'textDecoration': 'none', 'display': 'block', 'color': '#6c757d'}))
                ]))

            table = dbc.Table([
                html.Thead(html.Tr([html.Th("Название"), html.Th("Последнее изменение")])),
                html.Tbody(table_rows)
            ], hover=True, bordered=False, className="bg-white shadow-sm")

            return table, status_msg, clear_input

    except Exception as e:
        return html.Div(f"Системная ошибка БД: {e}", className="text-danger"), status_msg, dash.no_update