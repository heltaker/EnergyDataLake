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


# Генерация премиальных векторных SVG-иконок для вкладки "Все объекты" (Base64) - Каждая иконка записана в ОДНУ строчку
def get_vector_icon(item_type):
    if item_type == 'conn':
        return html.Span([
            html.Img(
                src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiMwZDZlZmQiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48cGF0aCBkPSJNMTQgMTVhNSA1IDAgMCAwLTcuNTQtLjU0bC0zIDNhNSA1IDAgMCAwIDcuMDcgNy4wN2wxLjcxLTEuNzEiPjwvcGF0aD48cGF0aCBkPSJNMTAgMTNhNSA1IDAgMCAwIDcuNTQuNTRsMy0zYTUgNSAwIDAgMC03LjA3LTcuMDdsLTEuNzIgMS43MSI+PC9wYXRoPjwvc3ZnPg==",
                style={'width': '24px', 'height': '24px', 'marginRight': '12px'})
        ], className="d-inline-flex align-items-center")
    elif item_type == 'ds':
        return html.Span([
            html.Img(
                src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiMxOWI4NjMiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48ZWxsaXBzZSBjeD0iMTIiIGN5PSI1IiByeD0iOSIgcnk9IjMiPjwvZWxsaXBzZT48cGF0aCBkPSJNMyA1djE0YTkgMyAwIDAgMCAxOCAwVjUiPjwvcGF0aD48cGF0aCBkPSJNMyAxMmE5IDMgMCAwIDAgMTggMCI+PC9wYXRoPjwvc3ZnPg==",
                style={'width': '24px', 'height': '24px', 'marginRight': '12px'})
        ], className="d-inline-flex align-items-center")
    else:
        return html.Span([
            html.Img(
                src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiMwZGNhZjAiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIj48bGluZSB4MT0iMTgiIHkxPSIyMCIgeDI9IjE4IiB5Mj0iMTAiPjwvbGluZT48bGluZSB4MT0iMTIiIHkxPSIyMCIgeDI9IjEyIiB5Mj0iNCI+PC9saW5lPjxsaW5lIHgxPSI2IiB5MT0iMjAiIHgyPSI2IiB5Mj0iMTQiPjwvbGluZT48L3N2Zz4=",
                style={'width': '24px', 'height': '24px', 'marginRight': '12px'})
        ], className="d-inline-flex align-items-center")


# ---------- Каскадное удаление (БД + файлы в MinIO) ----------
def _s3_delete(full_path):
    try:
        if full_path:
            bucket, key = full_path.split('/', 1)
            s3_client.delete_object(Bucket=bucket, Key=key)
    except Exception as e:
        print(f"Ошибка удаления S3 файла: {e}")


def delete_chart_db(conn, chart_id):
    conn.execute(text("DELETE FROM charts WHERE id = :id"), {"id": chart_id})


def delete_dataset_cascade(conn, ds_id):
    fp = conn.execute(text("SELECT file_path FROM datasets WHERE id = :id"), {"id": ds_id}).scalar()
    conn.execute(text("DELETE FROM charts WHERE dataset_id = :id"), {"id": ds_id})
    conn.execute(text("DELETE FROM datasets WHERE id = :id"), {"id": ds_id})
    if fp:
        _s3_delete(fp)


def delete_connection_cascade(conn, conn_id):
    raw = conn.execute(text("SELECT raw_file_path FROM connections WHERE id = :id"), {"id": conn_id}).scalar()
    ds_ids = [r[0] for r in conn.execute(text("SELECT id FROM datasets WHERE connection_id = :id"), {"id": conn_id})]
    for d in ds_ids:
        delete_dataset_cascade(conn, d)
    conn.execute(text("DELETE FROM connections WHERE id = :id"), {"id": conn_id})
    if raw:
        _s3_delete(raw)


def layout(ws_id=None, **kwargs):
    if not ws_id:
        return dbc.Container([html.H4("Рабочая область не выбрана", className="mt-5 text-danger"),
                              dbc.Button("К списку областей", href="/workspaces", color="primary")])

    return html.Div([
        dcc.Store(id='current-ws-id', data=ws_id),
        dcc.Store(id='ws-objects-refresh', data=0),
        dcc.Store(id='pending-delete-obj'),

        dbc.Container([
            # Хлебные крошки
            dbc.Button("← Вернуться к списку областей", href="/workspaces", color="link",
                       className="mb-3 px-0 text-decoration-none fw-bold text-primary"),

            # Заголовок рабочей области
            dbc.Row([
                dbc.Col([
                    html.H2(id="ws-title", className="fw-extrabold text-dark mb-1"),
                    html.P("Управляйте подключениями, настраивайте аналитические датасеты и визуализируйте графики",
                           className="text-muted small")
                ], width=7),
                dbc.Col([
                    dbc.ButtonGroup([
                        dbc.Button("Подключение", color="primary", href=f"/connection-builder?ws_id={ws_id}",
                                   className="fw-bold px-3 shadow-sm"),
                        dbc.Button("Датасет", color="success", href=f"/dataset-builder?ws_id={ws_id}",
                                   className="fw-bold px-3 shadow-sm"),
                        dbc.Button("График", color="info", href=f"/chart-builder?ws_id={ws_id}",
                                   className="text-white fw-bold px-3 shadow-sm"),
                    ])
                ], width=5, className="d-flex align-items-center justify-content-end")
            ], className="mb-4 align-items-center border-bottom pb-3"),

            # Макет Проводника данных
            dbc.Row([
                # Левая колонка: Умная панель фильтрации
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Фильтрация объектов", className="fw-bold text-dark bg-light border-0"),
                        dbc.CardBody([
                            # Мгновенный поиск (без debounce=True)
                            dbc.Label("Поиск по названию:", className="text-secondary small fw-bold uppercase mb-2"),
                            dbc.Input(id="search-objects", placeholder="Введите название для поиска...",
                                      className="mb-3 shadow-none border", type="text", debounce=False),

                            # Фильтр по типам
                            dbc.Label("Тип объекта:", className="text-secondary small fw-bold uppercase mb-2"),
                            dcc.Checklist(
                                id='filter-types',
                                options=[
                                    {'label': html.Span(' Подключения', className='ms-2 text-dark'), 'value': 'conn'},
                                    {'label': html.Span(' Датасеты', className='ms-2 text-dark'), 'value': 'ds'},
                                    {'label': html.Span(' Графики', className='ms-2 text-dark'), 'value': 'chart'}
                                ],
                                value=['conn', 'ds', 'chart'],
                                labelStyle={'display': 'block', 'marginBottom': '8px', 'cursor': 'pointer'},
                                className="mb-4"
                            ),

                            # Всплывающий календарь диапазона дат создания
                            dbc.Label("Временной интервал создания:",
                                      className="text-secondary small fw-bold uppercase mb-2"),
                            html.Div([
                                dcc.DatePickerRange(
                                    id='filter-create-date-range',
                                    start_date_placeholder_text="От",
                                    end_date_placeholder_text="До",
                                    clearable=True,
                                    number_of_months_shown=1,
                                    display_format='DD.MM.YYYY',
                                    className="mb-3 w-100"
                                )
                            ], className="w-100 mb-3"),

                            # Всплывающий календарь диапазона дат изменения
                            dbc.Label("Временной интервал изменения:",
                                      className="text-secondary small fw-bold uppercase mb-2"),
                            html.Div([
                                dcc.DatePickerRange(
                                    id='filter-update-date-range',
                                    start_date_placeholder_text="От",
                                    end_date_placeholder_text="До",
                                    clearable=True,
                                    number_of_months_shown=1,
                                    display_format='DD.MM.YYYY',
                                    className="mb-3 w-100"
                                )
                            ], className="w-100"),

                            html.Hr(),
                            dbc.Button("Сбросить фильтры", id="btn-reset-filters", color="secondary", outline=True,
                                       size="sm", className="w-100 fw-bold")
                        ])
                    ], className="border-0 shadow-sm rounded-3 mb-4")
                ], width=3),

                # Правая колонка: Интерактивный проводник объектов
                dbc.Col([
                    html.Div(id='ws-content-explorer', className="g-3")
                ], width=9)
            ]),

            # Модальное окно удаления
            dbc.Modal([
                dbc.ModalHeader(dbc.ModalTitle("Подтверждение удаления"), close_button=True),
                dbc.ModalBody(id="del-obj-modal-body"),
                dbc.ModalFooter([
                    dbc.Button("Отмена", id="btn-cancel-del-obj", color="secondary", outline=True,
                               className="px-3 fw-bold"),
                    dbc.Button("Подтвердить удаление", id="btn-confirm-del-obj", color="danger",
                               className="px-3 fw-bold")
                ])
            ], id="del-obj-modal", is_open=False, centered=True)
        ], className="mt-2")
    ])


@callback(
    Output('ws-title', 'children'),
    Output('ws-content-explorer', 'children'),
    Input('current-ws-id', 'data'),
    Input('auth-state', 'data'),
    Input('search-objects', 'value'),
    Input('filter-types', 'value'),
    Input('filter-create-date-range', 'start_date'),
    Input('filter-create-date-range', 'end_date'),
    Input('filter-update-date-range', 'start_date'),
    Input('filter-update-date-range', 'end_date'),
    Input('ws-objects-refresh', 'data')
)
def load_and_filter_explorer(ws_id, auth_state, search_text, selected_types,
                             start_create, end_create, start_update, end_update, refresh):
    if not auth_state or not auth_state.get('logged_in'):
        return "Загрузка...", html.Div("Синхронизация сессии...", className="text-muted text-center py-5")

    try:
        ws_id_int = int(ws_id)
        search_query = str(search_text).strip().lower() if search_text else ""

        with engine.connect() as conn:
            ws_name = conn.execute(text("SELECT name FROM workspaces WHERE id = :id"), {"id": ws_id_int}).scalar()

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

        items_all = []
        for r in conns:
            items_all.append({
                'id': r['id'], 'name': r['name'], 'type': 'conn', 'type_label': 'Подключение',
                'created': pd.to_datetime(r['created_at']),
                'updated': pd.to_datetime(r['updated_at']) if pd.notna(r['updated_at']) else pd.to_datetime(
                    r['created_at']),
                'type_key': 'conn', 'color': 'primary', 'href': f"/connection-builder?ws_id={ws_id}&conn_id={r['id']}"
            })
        for r in datasets:
            items_all.append({
                'id': r['id'], 'name': r['name'], 'type': 'ds', 'type_label': 'Датасет',
                'created': pd.to_datetime(r['created_at']),
                'updated': pd.to_datetime(r['updated_at']) if pd.notna(r['updated_at']) else pd.to_datetime(
                    r['created_at']),
                'type_key': 'ds', 'color': 'success', 'href': f"/dataset-builder?ws_id={ws_id}&ds_id={r['id']}"
            })
        for r in charts:
            items_all.append({
                'id': r['id'], 'name': r['name'], 'type': 'chart',
                'type_label': f"График ({chart_types_ru.get(r['chart_type'], r['chart_type'])})",
                'created': pd.to_datetime(r['created_at']),
                'updated': pd.to_datetime(r['updated_at']) if pd.notna(r['updated_at']) else pd.to_datetime(
                    r['created_at']),
                'type_key': 'chart', 'color': 'info', 'href': f"/chart-builder?ws_id={ws_id}&chart_id={r['id']}"
            })

        # Фильтрация в памяти
        filtered_items = items_all

        # 1. Поиск по названию
        if search_query:
            filtered_items = [i for i in filtered_items if search_query in i['name'].lower()]

        # 2. Фильтр по типам
        if selected_types:
            filtered_items = [i for i in filtered_items if i['type'] in selected_types]
        else:
            filtered_items = []

        # 3. Фильтр по диапазону дат создания (безопасное приведение через pd.notna)
        if start_create:
            s_dt = pd.to_datetime(start_create).date()
            filtered_items = [i for i in filtered_items if pd.notna(i['created']) and i['created'].date() >= s_dt]
        if end_create:
            e_dt = pd.to_datetime(end_create).date()
            filtered_items = [i for i in filtered_items if pd.notna(i['created']) and i['created'].date() <= e_dt]

        # 4. Фильтр по диапазону дат изменения (безопасное приведение через pd.notna)
        if start_update:
            su_dt = pd.to_datetime(start_update).date()
            filtered_items = [i for i in filtered_items if pd.notna(i['updated']) and i['updated'].date() >= su_dt]
        if end_update:
            eu_dt = pd.to_datetime(end_update).date()
            filtered_items = [i for i in filtered_items if pd.notna(i['updated']) and i['updated'].date() <= eu_dt]

        # Сортировка по изменению (новые первыми)
        filtered_items = sorted(filtered_items,
                                key=lambda x: x['updated'] if pd.notna(x['updated']) else pd.Timestamp.min,
                                reverse=True)

        if not filtered_items:
            explorer_view = html.Div([
                html.H5("Нет объектов, соответствующих критериям фильтрации", className="text-muted text-center my-5")
            ])
        else:
            cards = []
            for item in filtered_items:
                cards.append(
                    dbc.Col(
                        dbc.Card([
                            dbc.CardBody([
                                dbc.Row([
                                    # Профессиональные SVG иконки без смайликов
                                    dbc.Col([
                                        get_vector_icon(item['type_key'])
                                    ], width="auto", className="d-flex align-items-center"),

                                    dbc.Col([
                                        html.Div([
                                            dbc.Badge(item['type_label'], color=item['color'],
                                                      className="mb-2 text-white px-2 py-1"),
                                        ]),
                                        html.A(item['name'], href=item['href'],
                                               className="fw-bold text-dark fs-5 text-decoration-none hover-underline d-block mb-2"),
                                        html.Div([
                                            html.Span([html.I(className="bi bi-calendar-plus me-1"),
                                                       f"Создан: {item['created'].strftime('%d.%m.%Y %H:%M') if pd.notna(item['created']) else '—'}"],
                                                      className="text-muted small me-3"),
                                            html.Span([html.I(className="bi bi-pencil-square me-1"),
                                                       f"Изменен: {item['updated'].strftime('%d.%m.%Y %H:%M') if pd.notna(item['updated']) else '—'}"],
                                                      className="text-muted small")
                                        ], className="d-flex flex-wrap")
                                    ], className="ps-0"),

                                    dbc.Col([
                                        dbc.ButtonGroup([
                                            dbc.Button("Открыть", color="light", size="sm", href=item['href'],
                                                       className="border fw-bold"),
                                            dbc.Button("Удалить", color="danger", outline=True, size="sm",
                                                       id={'type': 'btn-del-obj', 'obj': item['type'],
                                                           'id': int(item['id']), 'name': str(item['name'])})
                                        ], className="shadow-none")
                                    ], width="auto", className="d-flex align-items-center justify-content-end")
                                ])
                            ])
                        ], className="border-0 shadow-sm rounded-3 mb-3 hover-shadow transition-all",
                            style={'backgroundColor': '#ffffff'})
                        , width=12)
                )
            explorer_view = dbc.Row(cards)

        return f"Рабочая область: {ws_name}", explorer_view

    except Exception as e:
        return "Ошибка", html.Div(f"Критическая ошибка загрузки компонентов: {e}", className="text-danger")


# Кнопка сброса фильтров
@callback(
    Output('search-objects', 'value'),
    Output('filter-types', 'value'),
    Output('filter-create-date-range', 'start_date'),
    Output('filter-create-date-range', 'end_date'),
    Output('filter-update-date-range', 'start_date'),
    Output('filter-update-date-range', 'end_date'),
    Input('btn-reset-filters', 'n_clicks'),
    prevent_initial_call=True
)
def reset_filters(n_clicks):
    if n_clicks:
        return "", ['conn', 'ds', 'chart'], None, None, None, None
    return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update


# Открытие модального окна удаления
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
        'conn': "Вместе с подключением будут каскадно удалены все связанные датасеты, графики и файлы в объектном хранилище MinIO.",
        'ds': "Вместе с датасетом будут каскадно удалены все построенные на нём графики и файлы обработанных датасетов в MinIO.",
        'chart': "График будет безвозвратно удалён из базы данных."
    }[trig['obj']]

    body = html.Div([
        html.P([f"Вы действительно хотите удалить {OBJ_LABELS[trig['obj']]} ", html.B(trig['name']), "?"],
               className="fs-5 mb-3"),
        dbc.Alert(warn, color="warning", className="mb-0 d-flex align-items-center small")
    ])
    return True, body, {'obj': trig['obj'], 'id': trig['id']}


# Подтверждение / отмена удаления
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
            with engine.begin() as conn:
                if pending['obj'] == 'chart':
                    delete_chart_db(conn, int(pending['id']))
                elif pending['obj'] == 'ds':
                    delete_dataset_cascade(conn, int(pending['id']))
                elif pending['obj'] == 'conn':
                    delete_connection_cascade(conn, int(pending['id']))
        except Exception as e:
            print(f"Ошибка удаления объекта: {e}")
        return False, (refresh or 0) + 1
    return dash.no_update, dash.no_update