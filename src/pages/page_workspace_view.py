# Страница: просмотр рабочей области (path='/workspace-view')
import dash
from dash import html, dcc, Input, Output, State, callback, ALL, ctx
import dash_bootstrap_components as dbc
import pandas as pd
import boto3
from sqlalchemy import create_engine, text

dash.register_page(__name__, path='/workspace-view')

POSTGRES_URI = "postgresql://admin:secret_password@localhost:5432/energy_lake"
engine = create_engine(POSTGRES_URI)
s3_client = boto3.client('s3', endpoint_url="http://localhost:9000",
                         aws_access_key_id="minio_admin", aws_secret_access_key="minio_password")

OBJ_LABELS = {'conn': 'подключение', 'ds': 'датасет', 'chart': 'чарт'}


# ---------- Каскадное удаление (БД + файлы в MinIO) ----------
def _s3_delete(full_path):
    try:
        if full_path:
            bucket, key = full_path.split('/', 1)
            s3_client.delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass


def delete_chart_db(conn, chart_id):
    conn.execute(text("DELETE FROM charts WHERE id = :id"), {"id": chart_id})


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


def layout(ws_id=None, **kwargs):
    if not ws_id:
        return dbc.Container([html.H4("Рабочая область не выбрана", className="mt-5 text-danger"),
                              dbc.Button("К списку областей", href="/workspaces", color="primary")])

    return html.Div([
        dcc.Store(id='current-ws-id', data=ws_id),
        dcc.Store(id='ws-objects-refresh', data=0),
        dcc.Store(id='ws-active-tab', data='tab-all'),
        dcc.Store(id='pending-delete-obj'),
        dbc.Container([
            dbc.Button("Вернуться в профиль (ко всем областям)", href="/workspaces", color="link",
                       className="mb-3 px-0"),
            html.H2(id="ws-title", className="mb-4 fw-bold text-dark"),

            # Оптимизированный поиск с debounce
            dbc.Input(id="search-objects", placeholder="Искать объекты по названию (нажмите Enter для поиска)...",
                      className="mb-4 shadow-sm", type="text", debounce=True),

            html.Div(id='ws-content'),

            # Модальное окно подтверждения удаления объекта
            dbc.Modal([
                dbc.ModalHeader(dbc.ModalTitle("Удаление объекта")),
                dbc.ModalBody(id="del-obj-modal-body"),
                dbc.ModalFooter([
                    dbc.Button("Отмена", id="btn-cancel-del-obj", color="secondary", outline=True),
                    dbc.Button("Удалить", id="btn-confirm-del-obj", color="danger")
                ])
            ], id="del-obj-modal", is_open=False, centered=True)
        ], className="mt-4")
    ])


@callback(
    Output('ws-title', 'children'), Output('ws-content', 'children'),
    Input('current-ws-id', 'data'), Input('auth-state', 'data'),
    Input('search-objects', 'value'),
    Input('ws-objects-refresh', 'data'),
    State('ws-active-tab', 'data')
)
def load_workspace_objects(ws_id, auth_state, search_text, refresh, active_tab):
    if not auth_state or not auth_state.get('logged_in'):
        return "Загрузка...", html.Div("Синхронизация сессии, пожалуйста, подождите...",
                                       className="text-muted text-center py-4")

    try:
        ws_id_int = int(ws_id)
        search_query = str(search_text).strip().lower() if search_text else ""

        with engine.connect() as conn:
            ws_name = conn.execute(text("SELECT name FROM workspaces WHERE id = :id"), {"id": ws_id_int}).scalar()

            # Добавлен занос поля updated_at во все три SQL-запроса
            conns = conn.execute(text(
                "SELECT id, name, created_at, updated_at FROM connections WHERE workspace_id = :ws"),
                {"ws": ws_id_int}).mappings().all()
            datasets = conn.execute(text(
                "SELECT d.id, d.name, d.created_at, d.updated_at FROM datasets d "
                "JOIN connections c ON d.connection_id = c.id WHERE c.workspace_id = :ws"),
                {"ws": ws_id_int}).mappings().all()
            charts = conn.execute(text(
                "SELECT ch.id, ch.name, ch.chart_type, ch.created_at, ch.updated_at FROM charts ch "
                "JOIN datasets d ON ch.dataset_id = d.id "
                "JOIN connections c ON d.connection_id = c.id WHERE c.workspace_id = :ws"),
                {"ws": ws_id_int}).mappings().all()

        chart_types_ru = {'bar': 'Столбчатая диаграмма', 'line': 'Линейная диаграмма',
                          'scatter': 'Точечная диаграмма', 'pie': 'Круговая диаграмма'}

        # Унифицированное представление объектов-"файлов" с поддержкой updated_at
        def make_item(row, obj, href, extra=None):
            return {'id': row['id'], 'name': row['name'], 'obj': obj, 'href': href,
                    'created': pd.to_datetime(row['created_at']),
                    'updated': pd.to_datetime(row['updated_at']) if pd.notna(row['updated_at']) else None,
                    'extra': extra}

        items_conn = [make_item(r, 'conn', f"/connection-builder?ws_id={ws_id}&conn_id={r['id']}")
                      for r in conns]
        items_ds = [make_item(r, 'ds', f"/dataset-builder?ws_id={ws_id}&ds_id={r['id']}")
                    for r in datasets]
        items_chart = [make_item(r, 'chart', f"/chart-builder?ws_id={ws_id}&chart_id={r['id']}",
                                 extra=chart_types_ru.get(r['chart_type'], r['chart_type']))
                       for r in charts]

        if search_query:
            items_conn = [i for i in items_conn if search_query in str(i['name']).lower()]
            items_ds = [i for i in items_ds if search_query in str(i['name']).lower()]
            items_chart = [i for i in items_chart if search_query in str(i['name']).lower()]

        items_all = sorted(items_conn + items_ds + items_chart, key=lambda i: i['created'], reverse=True)

        category_ru = {'conn': 'Подключение', 'ds': 'Датасет', 'chart': 'Чарт'}

        # Сборка таблиц с новыми колонками дат изменения
        def build_table(items, tab_type):
            if not items:
                return html.Div("Нет объектов", className="text-muted text-center py-4 fs-5")

            # Везде добавляем Th("Дата изменения")
            if tab_type == 'all':
                headers = [html.Th("Название"), html.Th("Тип объекта"), html.Th("Дата создания"),
                           html.Th("Дата изменения"), html.Th("")]
            elif tab_type == 'charts':
                headers = [html.Th("Название"), html.Th("Тип графика"), html.Th("Дата создания"),
                           html.Th("Дата изменения"), html.Th("")]
            else:
                headers = [html.Th("Название"), html.Th("Дата создания"), html.Th("Дата изменения"), html.Th("")]

            link_style = {'textDecoration': 'none', 'display': 'block'}
            table_rows = []
            for it in items:
                created_str = it['created'].strftime('%d.%m.%Y %H:%M') if pd.notna(it['created']) else "—"
                updated_str = it['updated'].strftime('%d.%m.%Y %H:%M') if it['updated'] and pd.notna(
                    it['updated']) else "—"

                name_cell = html.Td(html.A(it['name'], href=it['href'],
                                           style={**link_style, 'fontWeight': 'bold'}))
                actions = html.Td(dbc.ButtonGroup([
                    dbc.Button("Открыть", color="primary", size="sm", outline=True, href=it['href']),
                    dbc.Button("Удалить", color="danger", size="sm", outline=True,
                               id={'type': 'btn-del-obj', 'obj': it['obj'], 'id': int(it['id']),
                                   'name': str(it['name'])})
                ]), style={'width': '180px', 'textAlign': 'right'})

                if tab_type == 'all':
                    tds = [name_cell,
                           html.Td(category_ru[it['obj']] if it['obj'] != 'chart' or not it['extra']
                                   else category_ru['chart'], className="text-secondary"),
                           html.Td(created_str, className="text-muted"),
                           html.Td(updated_str, className="text-muted"),
                           actions]
                elif tab_type == 'charts':
                    tds = [name_cell,
                           html.Td(it['extra'], className="text-secondary"),
                           html.Td(created_str, className="text-muted"),
                           html.Td(updated_str, className="text-muted"),
                           actions]
                else:
                    tds = [name_cell,
                           html.Td(created_str, className="text-muted"),
                           html.Td(updated_str, className="text-muted"),
                           actions]
                table_rows.append(html.Tr(tds))

            return dbc.Table([html.Thead(html.Tr(headers)), html.Tbody(table_rows)], hover=True, striped=True,
                             bordered=False, className="bg-white shadow-sm mt-3")

        tabs = dbc.Tabs([
            dbc.Tab(label="Все объекты", tab_id="tab-all",
                    children=[html.Br(), build_table(items_all, 'all')]),
            dbc.Tab(label="Подключения", tab_id="tab-conn", children=[
                html.Br(), dbc.Button("Создать подключение", color="primary", size="sm",
                                      href=f"/connection-builder?ws_id={ws_id}"), build_table(items_conn, 'conn')
            ]),
            dbc.Tab(label="Датасеты", tab_id="tab-ds", children=[
                html.Br(),
                dbc.Button("Создать датасет", color="success", size="sm", href=f"/dataset-builder?ws_id={ws_id}"),
                build_table(items_ds, 'ds')
            ]),
            dbc.Tab(label="Чарты", tab_id="tab-charts", children=[
                html.Br(), dbc.Button("Создать чарт", color="info", size="sm", className="text-white",
                                      href=f"/chart-builder?ws_id={ws_id}"), build_table(items_chart, 'charts')
            ])
        ], id="ws-tabs", active_tab=active_tab or "tab-all", className="mt-3")

        return f"Рабочая область: {ws_name}", tabs
    except Exception as e:
        return "Ошибка", html.Div(f"Критическая ошибка загрузки компонентов: {e}", className="text-danger")


# Запоминаем активную вкладку, чтобы она не сбрасывалась после удаления
@callback(Output('ws-active-tab', 'data'), Input('ws-tabs', 'active_tab'), prevent_initial_call=True)
def remember_tab(active_tab):
    return active_tab


# Открытие модального окна подтверждения удаления объекта
@callback(
    Output('del-obj-modal', 'is_open'),
    Output('del-obj-modal-body', 'children'),
    Output('pending-delete-obj', 'data'),
    Input({'type': 'btn-del-obj', 'obj': ALL, 'id': ALL, 'name': ALL}, 'n_clicks'),
    prevent_initial_call=True
)
def open_delete_obj_modal(n_clicks):
    if not ctx.triggered or ctx.triggered[0]['value'] in (None, 0):
        return dash.no_update, dash.no_update, dash.no_update
    trig = ctx.triggered_id
    warn = {
        'conn': "Вместе с подключением будут удалены его датасеты, чарты и файлы в хранилище.",
        'ds': "Вместе с датасетом будут удалены построенные на нём чарты и файл в хранилище.",
        'chart': "Чарт будет удалён без возможности восстановления."
    }[trig['obj']]
    body = html.Div([
        html.P([f"Удалить {OBJ_LABELS[trig['obj']]} ", html.B(trig['name']), "?"], className="mb-2"),
        html.P(warn, className="text-muted small mb-0")
    ])
    return True, body, {'obj': trig['obj'], 'id': trig['id']}


# Подтверждение / отмена удаления объекта
@callback(
    Output('del-obj-modal', 'is_open', allow_duplicate=True),
    Output('ws-objects-refresh', 'data'),
    Input('btn-confirm-del-obj', 'n_clicks'),
    Input('btn-cancel-del-obj', 'n_clicks'),
    State('pending-delete-obj', 'data'),
    State('ws-objects-refresh', 'data'),
    prevent_initial_call=True
)
def confirm_delete_obj(n_confirm, n_cancel, pending, refresh):
    if ctx.triggered_id == 'btn-cancel-del-obj':
        return False, dash.no_update
    if ctx.triggered_id == 'btn-confirm-del-obj' and pending:
        try:
            with engine.connect() as conn:
                if pending['obj'] == 'chart':
                    delete_chart_db(conn, int(pending['id']))
                elif pending['obj'] == 'ds':
                    delete_dataset_cascade(conn, int(pending['id']))
                elif pending['obj'] == 'conn':
                    delete_connection_cascade(conn, int(pending['id']))
                conn.commit()
        except Exception as e:
            print(f"Ошибка удаления объекта: {e}")
        return False, (refresh or 0) + 1
    return dash.no_update, dash.no_update