import dash
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc

# Включаем многостраничный режим
app = dash.Dash(__name__, use_pages=True, external_stylesheets=[dbc.themes.FLATLY], suppress_callback_exceptions=True)

# Оптимизированная структура стилей
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            html, body {
                height: 100%;
                margin: 0;
                padding: 0;
                overflow: hidden; /* Отключаем глобальный скролл */
                background-color: #f8f9fa;
            }

            /* Фиксируем высоту технических контейнеров Dash */
            #react-entry-point, ._dash-app-content, #_dash-layout {
                height: 100% !important;
                width: 100% !important;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }

            /* Сетка: Шапка (ровно 60px) + Контент (все остальное пространство) */
            .app-container {
                display: grid;
                grid-template-rows: 60px 1fr;
                height: 100vh;
                width: 100vw;
                overflow: hidden;
            }

            /* Принудительно задаем абсолютно одинаковую высоту для навигационной панели */
            #main-navbar {
                z-index: 1000;
                height: 60px !important;
                padding-top: 0 !important;
                padding-bottom: 0 !important;
                display: flex;
                align-items: center;
                box-sizing: border-box;
            }

            /* Выравниваем элементы внутри контейнеров Bootstrap строго по центру */
            #main-navbar > .container-fluid, #main-navbar > .container {
                height: 100% !important;
                display: flex !important;
                align-items: center !important;
                justify-content: space-between;
            }

            /* Вертикальное центрирование элементов меню */
            #main-navbar .navbar-nav {
                display: flex !important;
                align-items: center !important;
                flex-direction: row !important;
                height: 100%;
            }

            #main-navbar .nav-item {
                display: flex;
                align-items: center;
                height: 100%;
            }

            /* Сброс лишних внешних отступов у ссылок и кнопок в шапке */
            #main-navbar .nav-link, #main-navbar .btn {
                margin-top: 0 !important;
                margin-bottom: 0 !important;
                display: inline-flex;
                align-items: center;
            }

            /* Контейнер прокрутки под шапкой */
            .scroll-container {
                overflow-y: auto !important; 
                scrollbar-gutter: stable; /* Предотвращаем сдвиг контента */
                background-color: #f8f9fa;
                height: 100%;
                min-height: 0;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

# Применяем правильную архитектуру разметки:
# Невизуальные компоненты лежат на самом верхнем уровне,
# а в Grid-сетку (.app-container) входят ТОЛЬКО шапка и контент.
app.layout = html.Div([
    # Невидимые служебные компоненты
    dcc.Store(id='auth-state', data={'logged_in': False, 'username': None, 'user_id': None}, storage_type='session'),
    dcc.Location(id='global-url', refresh=True),

    # Основной визуальный макет приложения
    html.Div([
        # Динамическая навигационная панель (строка 1: 60px)
        dbc.NavbarSimple(
            brand="Energy Data Platform",
            color="dark",
            dark=True,
            className="shadow",
            id="main-navbar",
            children=[]
        ),

        # Область отображения страниц (строка 2: 1fr)
        html.Div(
            dbc.Container(dash.page_container, fluid=True, className="pt-4 pb-5"),
            className="scroll-container"
        )
    ], className="app-container")
])


# Логика обновления шапки: автоматическое выравнивание без ручных margin-отступов
@callback(
    Output('main-navbar', 'children'),
    Input('auth-state', 'data')
)
def update_navbar(auth_state):
    if auth_state and auth_state.get('logged_in'):
        return [
            dbc.NavItem(dbc.NavLink(f"Пользователь: {auth_state['username']}", disabled=True, className="text-light")),
            dbc.NavItem(dbc.Button("Выйти", id="btn-logout", color="danger", size="sm", className="ms-3"))
        ]
    return []


# Логика кнопки Выход
@callback(
    Output('auth-state', 'data', allow_duplicate=True),
    Output('global-url', 'pathname'),
    Input('btn-logout', 'n_clicks'),
    prevent_initial_call=True
)
def handle_logout(n_clicks):
    if n_clicks:
        return {'logged_in': False, 'username': None, 'user_id': None}, '/'
    return dash.no_update, dash.no_update


if __name__ == '__main__':
    print("Запуск Multi-Page Dash сервера на http://127.0.0.1:8050/")
    app.run(debug=True, dev_tools_ui=False, port=8050)