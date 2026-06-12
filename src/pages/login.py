import dash
from dash import html, dcc, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
from sqlalchemy import create_engine, text

dash.register_page(__name__, path='/')

POSTGRES_URI = "postgresql://admin:secret_password@localhost:5432/energy_lake"
engine = create_engine(POSTGRES_URI)

layout = dbc.Container([
    dcc.Location(id='url-login', refresh=True),
    dbc.Row([
        dbc.Col(dbc.Card([
            dbc.CardHeader(html.H3("Доступ к системе", className="text-center")),
            dbc.CardBody([
                dbc.Input(id="auth-username", type="text", placeholder="Логин", className="mb-3"),
                dbc.Input(id="auth-password", type="password", placeholder="Пароль", className="mb-4"),
                dbc.Row([
                    dbc.Col(dbc.Button("Войти", id="btn-login", color="primary", className="w-100"), width=6),
                    dbc.Col(dbc.Button("Регистрация", id="btn-register", color="success", outline=True, className="w-100"), width=6)
                ]),
                html.Div(id="auth-output", className="mt-4 text-center fw-bold")
            ])
        ], className="shadow"), width=4)
    ], justify="center", className="mt-5 pt-5")
])

@callback(
    Output('auth-state', 'data', allow_duplicate=True),
    Output('auth-output', 'children'),
    Output('url-login', 'pathname'),
    Input('btn-login', 'n_clicks'),
    Input('btn-register', 'n_clicks'),
    State('auth-username', 'value'),
    State('auth-password', 'value'), prevent_initial_call=True
)
def handle_auth(n_login, n_register, username, password):
    triggered_id = ctx.triggered_id
    if not username or not password: return dash.no_update, html.Span("Заполните все поля",
                                                                      className="text-danger"), dash.no_update
    try:
        with (engine.connect() as conn):
            if triggered_id == 'btn-login':
                result = conn.execute(text("SELECT id FROM users WHERE username = :u AND password = :p"),
                                      {"u": username, "p": password}).fetchone()
                if result: return {'logged_in': True, 'username': username, 'user_id': result[0]}, "", '/workspaces'
                else: return dash.no_update, html.Span("Неверный логин или пароль", className="text-danger"),
                dash.no_update
            elif triggered_id == 'btn-register':
                if conn.execute(text("SELECT id FROM users WHERE username = :u"), {"u": username}).fetchone():
                    return dash.no_update, html.Span("Этот логин уже занят", className="text-danger"), dash.no_update
                conn.execute(text("INSERT INTO users (username, password) VALUES (:u, :p)"),
                             {"u": username, "p": password})
                conn.commit()
                return dash.no_update, html.Span("Успех! Теперь нажмите 'Войти'", className="text-success"), dash.no_update
    except Exception as e: return dash.no_update, html.Span(f"Ошибка БД: {e}", className="text-danger"), dash.no_update