# Страница: список рабочих областей (path='/workspaces')
import dash
from dash import html, dcc, Input, Output, State, callback, ALL, ctx
import dash_bootstrap_components as dbc
import pandas as pd
import boto3
from sqlalchemy import create_engine, text

dash.register_page(__name__, path='/workspaces')

POSTGRES_URI = "postgresql://admin:secret_password@localhost:5432/energy_lake"
engine = create_engine(POSTGRES_URI)
s3_client = boto3.client('s3', endpoint_url="http://localhost:9000",
                         aws_access_key_id="minio_admin", aws_secret_access_key="minio_password")

try:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS workspaces (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()
except Exception as e:
    print(f"Ошибка инициализации таблицы областей: {e}")


# ---------- Каскадное удаление (БД + файлы в MinIO) ----------
def _s3_delete(full_path):
    """Удаляет файл в MinIO по пути вида 'bucket/key'. Ошибки игнорируются."""
    try:
        if full_path:
            bucket, key = full_path.split('/', 1)
            s3_client.delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass


def delete_dataset_cascade(conn, ds_id):
    fp = conn.execute(text("SELECT file_path FROM datasets WHERE id = :id"), {"id": ds_id}).scalar()
    conn.execute(text("DELETE FROM charts WHERE dataset_id = :id"), {"id": ds_id})
    conn.execute(text("DELETE FROM datasets WHERE id = :id"), {"id": ds_id})
    _s3_delete(fp)


def delete_connection_cascade(conn, conn_id):
    raw = conn.execute(text("SELECT raw_file_path FROM connections WHERE id = :id"), {"id": conn_id}).scalar()
    ds_ids = [r[0] for r in conn.execute(text("SELECT id FROM datasets WHERE connection_id = :id"), {"id": conn_id})]
    for d in ds_ids:
        delete_dataset_cascade(conn, d)
    conn.execute(text("DELETE FROM connections WHERE id = :id"), {"id": conn_id})
    _s3_delete(raw)


def delete_workspace_cascade(conn, ws_id):
    conn_ids = [r[0] for r in conn.execute(text("SELECT id FROM connections WHERE workspace_id = :id"), {"id": ws_id})]
    for c in conn_ids:
        delete_connection_cascade(conn, c)
    conn.execute(text("DELETE FROM workspaces WHERE id = :id"), {"id": ws_id})


layout = dbc.Container([
    dcc.Location(id='url-workspaces-list', refresh=True),
    dcc.Store(id='ws-list-refresh', data=0),
    dcc.Store(id='pending-delete-ws'),

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

    html.Div(id='workspaces-grid', className="mt-4"),

    # Модальное окно подтверждения удаления
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Удаление рабочей области")),
        dbc.ModalBody(id="del-ws-modal-body"),
        dbc.ModalFooter([
            dbc.Button("Отмена", id="btn-cancel-del-ws", color="secondary", outline=True),
            dbc.Button("Удалить", id="btn-confirm-del-ws", color="danger")
        ])
    ], id="del-ws-modal", is_open=False, centered=True)
], fluid=True, className="px-4")


@callback(
    Output('workspaces-grid', 'children'),
    Output('create-ws-status', 'children'),
    Output('new-workspace-name', 'value'),
    Input('auth-state', 'data'),
    Input('btn-create-workspace', 'n_clicks'),
    Input('search-workspaces', 'value'),
    Input('ws-list-refresh', 'data'),
    State('new-workspace-name', 'value')
)
def render_workspaces(auth_state, n_clicks, search_text, refresh, new_name):
    if not auth_state or not auth_state.get('logged_in'):
        return html.Div("Загрузка сессии...", className="text-muted text-center mt-5"), "", dash.no_update

    user_id = auth_state['user_id']
    status_msg = ""
    clear_input = dash.no_update

    triggered = ctx.triggered[0]['prop_id'] if ctx.triggered else ""

    try:
        with engine.connect() as conn:
            if 'btn-create-workspace' in triggered:
                if new_name:
                    # При создании явно задаем и created_at, и updated_at
                    conn.execute(text(
                        "INSERT INTO workspaces (user_id, name, created_at, updated_at) VALUES (:u, :n, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                                 {"u": user_id, "n": new_name})
                    conn.commit()
                    clear_input = ""
                else:
                    status_msg = "Укажите название рабочей области"

            # Запрашиваем из базы как created_at, так и updated_at
            df = pd.read_sql(
                text(
                    "SELECT id, name, created_at, updated_at FROM workspaces WHERE user_id = :uid ORDER BY created_at DESC"),
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
                created_val = pd.to_datetime(row['created_at']).strftime('%d.%m.%Y %H:%M')
                # Безопасно парсим updated_at, если он заполнен
                updated_val = pd.to_datetime(row['updated_at']).strftime('%d.%m.%Y %H:%M') if pd.notna(
                    row['updated_at']) else "—"

                table_rows.append(html.Tr([
                    html.Td(html.A(row['name'], href=link_url,
                                   style={'textDecoration': 'none', 'display': 'block', 'fontWeight': 'bold'})),
                    html.Td(html.A(created_val, href=link_url,
                                   style={'textDecoration': 'none', 'display': 'block', 'color': '#6c757d'})),
                    html.Td(html.A(updated_val, href=link_url,
                                   style={'textDecoration': 'none', 'display': 'block', 'color': '#6c757d'})),
                    html.Td(dbc.Button("Удалить", color="danger", size="sm", outline=True,
                                       id={'type': 'btn-del-ws', 'id': int(row['id']), 'name': str(row['name'])}),
                            style={'width': '120px', 'textAlign': 'right'})
                ]))

            # Добавлена колонка "Дата изменения" в заголовок таблицы
            table = dbc.Table([
                html.Thead(
                    html.Tr([html.Th("Название"), html.Th("Дата создания"), html.Th("Дата изменения"), html.Th("")])),
                html.Tbody(table_rows)
            ], hover=True, bordered=False, className="bg-white shadow-sm")

            return table, status_msg, clear_input

    except Exception as e:
        return html.Div(f"Системная ошибка БД: {e}", className="text-danger"), status_msg, dash.no_update


# Открытие модального окна подтверждения
@callback(
    Output('del-ws-modal', 'is_open'),
    Output('del-ws-modal-body', 'children'),
    Output('pending-delete-ws', 'data'),
    Input({'type': 'btn-del-ws', 'id': ALL, 'name': ALL}, 'n_clicks'),
    prevent_initial_call=True
)
def open_delete_modal(n_clicks):
    if not ctx.triggered or ctx.triggered[0]['value'] in (None, 0):
        return dash.no_update, dash.no_update, dash.no_update
    trig = ctx.triggered_id
    body = html.Div([
        html.P([f"Удалить рабочую область ", html.B(trig['name']), "?"], className="mb-2"),
        html.P("Будут удалены все её подключения, датасеты, чарты и связанные файлы в хранилище. "
               "Действие необратимо.", className="text-muted small mb-0")
    ])
    return True, body, trig['id']


# Подтверждение / отмена удаления
@callback(
    Output('del-ws-modal', 'is_open', allow_duplicate=True),
    Output('ws-list-refresh', 'data'),
    Input('btn-confirm-del-ws', 'n_clicks'),
    Input('btn-cancel-del-ws', 'n_clicks'),
    State('pending-delete-ws', 'data'),
    State('ws-list-refresh', 'data'),
    prevent_initial_call=True
)
def confirm_delete(n_confirm, n_cancel, ws_id, refresh):
    if ctx.triggered_id == 'btn-cancel-del-ws':
        return False, dash.no_update
    if ctx.triggered_id == 'btn-confirm-del-ws' and ws_id:
        try:
            with engine.connect() as conn:
                delete_workspace_cascade(conn, int(ws_id))
                conn.commit()
        except Exception as e:
            print(f"Ошибка удаления области: {e}")
        return False, (refresh or 0) + 1
    return dash.no_update, dash.no_update