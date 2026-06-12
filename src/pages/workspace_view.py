import dash
from dash import html, dcc, Input, Output, callback
import dash_bootstrap_components as dbc
import pandas as pd
from sqlalchemy import create_engine, text

dash.register_page(__name__, path='/workspace-view')

POSTGRES_URI = "postgresql://admin:secret_password@localhost:5432/energy_lake"
engine = create_engine(POSTGRES_URI)


def layout(ws_id=None, **kwargs):
    if not ws_id:
        return dbc.Container([html.H4("Рабочая область не выбрана", className="mt-5 text-danger"),
                              dbc.Button("К списку областей", href="/workspaces", color="primary")])

    return html.Div([
        dcc.Store(id='current-ws-id', data=ws_id),
        dbc.Container([
            dbc.Button("Вернуться в профиль (ко всем областям)", href="/workspaces", color="link",
                       className="mb-3 px-0"),
            html.H2(id="ws-title", className="mb-4 fw-bold text-dark"),

            # Оптимизированный поиск с debounce
            dbc.Input(id="search-objects", placeholder="Искать объекты по названию (нажмите Enter для поиска)...",
                      className="mb-4 shadow-sm", type="text", debounce=True),

            html.Div(id='ws-content')
        ], className="mt-4")
    ])


@callback(
    Output('ws-title', 'children'), Output('ws-content', 'children'),
    Input('current-ws-id', 'data'), Input('auth-state', 'data'),
    Input('search-objects', 'value')
)
def load_workspace_objects(ws_id, auth_state, search_text):
    if not auth_state or not auth_state.get('logged_in'):
        return "Загрузка...", html.Div("Синхронизация сессии, пожалуйста, подождите...",
                                       className="text-muted text-center py-4")

    try:
        ws_id_int = int(ws_id)
        search_query = str(search_text).strip() if search_text else ""

        with engine.connect() as conn:
            ws_name = conn.execute(text("SELECT name FROM workspaces WHERE id = :id"), {"id": ws_id_int}).scalar()

            df_conn = pd.read_sql(
                text("SELECT name AS Название, created_at AS Создано FROM connections WHERE workspace_id = :ws"), conn,
                params={"ws": ws_id_int})
            df_ds = pd.read_sql(text(
                "SELECT d.name AS Название, d.created_at AS Создано FROM datasets d JOIN connections c ON d.connection_id = c.id WHERE c.workspace_id = :ws"),
                                conn, params={"ws": ws_id_int})
            df_charts = pd.read_sql(text(
                "SELECT ch.name AS Название, ch.chart_type AS Тип, ch.created_at AS Создано FROM charts ch JOIN datasets d ON ch.dataset_id = d.id JOIN connections c ON d.connection_id = c.id WHERE c.workspace_id = :ws"),
                                    conn, params={"ws": ws_id_int})

            # Надежный поиск без использования regex
            if search_query:
                if not df_conn.empty: df_conn = df_conn[
                    df_conn['Название'].str.contains(search_query, case=False, na=False, regex=False)]
                if not df_ds.empty: df_ds = df_ds[
                    df_ds['Название'].str.contains(search_query, case=False, na=False, regex=False)]
                if not df_charts.empty: df_charts = df_charts[
                    df_charts['Название'].str.contains(search_query, case=False, na=False, regex=False)]

            chart_types_ru = {'bar': 'Столбчатая диаграмма', 'line': 'Линейная диаграмма',
                              'scatter': 'Точечная диаграмма', 'pie': 'Круговая диаграмма'}
            if not df_charts.empty: df_charts['Тип'] = df_charts['Тип'].map(chart_types_ru).fillna(df_charts['Тип'])

            # Безопасный сбор данных для вкладки Все объекты (сортировка до форматирования)
            frames = []
            if not df_conn.empty: frames.append(df_conn.assign(Категория='Подключение'))
            if not df_ds.empty: frames.append(df_ds.assign(Категория='Датасет'))
            if not df_charts.empty: frames.append(df_charts.assign(Категория='Чарт'))

            if frames:
                df_all = pd.concat(frames)
                df_all['Создано'] = pd.to_datetime(df_all['Создано'])
                df_all = df_all.sort_values(by='Создано', ascending=False)
                df_all['Создано'] = df_all['Создано'].dt.strftime('%d.%m.%Y %H:%M')
            else:
                df_all = pd.DataFrame(columns=['Название', 'Категория', 'Создано'])

            # Форматирование дат для отдельных вкладок
            for df in [df_conn, df_ds, df_charts]:
                if not df.empty: df['Создано'] = pd.to_datetime(df['Создано']).dt.strftime('%d.%m.%Y %H:%M')

            # Монолитная ручная сборка таблиц (Защита от сбоев индексации Pandas)
            def build_table(df, tab_type):
                if df.empty:
                    return html.Div("Нет объектов", className="text-muted text-center py-4 fs-5")

                if tab_type == 'all':
                    headers = [html.Th("Название"), html.Th("Тип объекта"), html.Th("Дата создания")]
                elif tab_type == 'charts':
                    headers = [html.Th("Название"), html.Th("Тип графика"), html.Th("Дата создания")]
                else:
                    headers = [html.Th("Название"), html.Th("Дата создания")]

                table_rows = []
                for _, row in df.iterrows():
                    if tab_type == 'all':
                        tds = [html.Td(row['Название'], className="fw-bold text-dark"),
                               html.Td(row['Категория'], className="text-secondary"),
                               html.Td(row['Создано'], className="text-muted")]
                    elif tab_type == 'charts':
                        tds = [html.Td(row['Название'], className="fw-bold text-dark"),
                               html.Td(row['Тип'], className="text-secondary"),
                               html.Td(row['Создано'], className="text-muted")]
                    else:
                        tds = [html.Td(row['Название'], className="fw-bold text-dark"),
                               html.Td(row['Создано'], className="text-muted")]
                    table_rows.append(html.Tr(tds))

                return dbc.Table([html.Thead(html.Tr(headers)), html.Tbody(table_rows)], hover=True, striped=True,
                                 bordered=False, className="bg-white shadow-sm mt-3")

            tabs = dbc.Tabs([
                dbc.Tab(label="Все объекты", tab_id="tab-all",
                        children=[html.Br(), build_table(df_all, 'all')]),
                dbc.Tab(label="Подключения", tab_id="tab-conn", children=[
                    html.Br(), dbc.Button("Создать подключение", color="primary", size="sm",
                                          href=f"/connection-builder?ws_id={ws_id}"), build_table(df_conn, 'conn')
                ]),
                dbc.Tab(label="Датасеты", tab_id="tab-ds", children=[
                    html.Br(),
                    dbc.Button("Создать датасет", color="success", size="sm", href=f"/dataset-builder?ws_id={ws_id}"),
                    build_table(df_ds, 'ds')
                ]),
                dbc.Tab(label="Чарты", tab_id="tab-charts", children=[
                    html.Br(), dbc.Button("Создать чарт", color="info", size="sm", className="text-white",
                                          href=f"/chart-builder?ws_id={ws_id}"), build_table(df_charts, 'charts')
                ])
            ], id="ws-tabs", active_tab="tab-all", className="mt-3")

            return f"Рабочая область: {ws_name}", tabs
    except Exception as e:
        return "Ошибка", html.Div(f"Критическая ошибка загрузки компонентов: {e}", className="text-danger")