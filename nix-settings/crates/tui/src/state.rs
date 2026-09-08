use crate::{
    confirmation::{ConfirmPrompt, ConfirmStatus},
    float::{Float, FloatContent},
    hint::{create_shortcut_list, Shortcut},
    running_command::RunningCommand,
    shortcuts,
    system_info::SystemInfo,
    theme::Theme,
};
use nix_settings_core::{
    apply_command, categories, Command, DesiredState, MenuItem, SystemSnapshot,
};
use ratatui::{
    crossterm::event::{KeyCode, KeyEvent, KeyModifiers, MouseEvent},
    layout::{Constraint, Layout, Rect},
    prelude::*,
    symbols::border,
    widgets::{Block, Borders, List, ListItem, ListState, Paragraph},
};

const MIN_WIDTH: u16 = 100;
const MIN_HEIGHT: u16 = 25;
const FLOAT_SIZE: u16 = 95;
const CONFIRM_SIZE: u16 = 44;

#[derive(Clone, Copy, PartialEq, Eq)]
enum Focus {
    Categories,
    Items,
    Search,
    Configure,
    Floating,
    Confirmation,
}

pub struct AppState {
    theme: Theme,
    mouse_enabled: bool,
    size_bypass: bool,
    snapshot: SystemSnapshot,
    categories: Vec<nix_settings_core::Category>,
    category_state: ListState,
    item_state: ListState,
    focus: Focus,
    search: String,
    system_info: Option<SystemInfo>,
    float: Option<Float<RunningCommand>>,
    confirm: Option<Float<ConfirmPrompt>>,
    pending: Option<Command>,
    desired: DesiredState,
    desired_dirty: bool,
}

impl AppState {
    pub fn new(theme: Theme, mouse_enabled: bool, size_bypass: bool) -> Self {
        let snapshot = nix_settings_core::snapshot().unwrap_or_else(|_| SystemSnapshot {
            host: "unknown".into(),
            profile: "unknown".into(),
            branch: "unknown".into(),
            commit: "unknown".into(),
            dirty: false,
            generation: "unknown".into(),
            nixos_version: "unknown".into(),
            repo: std::env::current_dir().unwrap_or_default(),
        });
        let desired = DesiredState::load(&snapshot.repo, &snapshot.host).unwrap_or(DesiredState {
            schema: 1,
            desktops: vec!["mango".into()],
            default_session: "mango".into(),
            shell: "noctalia".into(),
            bundles: Default::default(),
            browser: Default::default(),
            integrations: Default::default(),
        });
        let categories = categories(&snapshot);
        Self {
            theme,
            mouse_enabled,
            size_bypass,
            snapshot,
            categories,
            category_state: ListState::default().with_selected(Some(0)),
            item_state: ListState::default().with_selected(Some(0)),
            focus: Focus::Items,
            search: String::new(),
            system_info: SystemInfo::gather(),
            float: None,
            confirm: None,
            pending: None,
            desired,
            desired_dirty: false,
        }
    }

    fn selected_category(&self) -> usize {
        self.category_state.selected().unwrap_or(0)
    }
    fn category_name(&self) -> &str {
        self.categories
            .get(self.selected_category())
            .map(|c| c.name)
            .unwrap_or("Overview")
    }

    fn configure_items(&self) -> Vec<MenuItem> {
        let enabled = |name: &str| self.desired.desktops.iter().any(|d| d == name);
        vec![
            MenuItem::info(
                format!("[{}] Mango", if enabled("mango") { "x" } else { " " }),
                "Toggle Mango compositor",
            ),
            MenuItem::info(
                format!("[{}] Hyprland", if enabled("hyprland") { "x" } else { " " }),
                "Toggle Hyprland compositor",
            ),
            MenuItem::info(
                format!("[{}] Niri", if enabled("niri") { "x" } else { " " }),
                "Toggle Niri compositor",
            ),
            MenuItem::info(
                format!("Shell: {}", self.desired.shell),
                "Cycle Noctalia / Caelestia",
            ),
            MenuItem::info(
                format!("Default session: {}", self.desired.default_session),
                "Cycle enabled compositors",
            ),
            MenuItem::info(
                format!(
                    "[{}] Gaming bundle",
                    if self.desired.bundles.gaming {
                        "x"
                    } else {
                        " "
                    }
                ),
                "Gaming software bundle",
            ),
            MenuItem::info(
                format!(
                    "[{}] Office bundle",
                    if self.desired.bundles.office {
                        "x"
                    } else {
                        " "
                    }
                ),
                "Office software bundle",
            ),
            MenuItem::info(
                format!(
                    "[{}] Development bundle",
                    if self.desired.bundles.development {
                        "x"
                    } else {
                        " "
                    }
                ),
                "Development software bundle",
            ),
            MenuItem::info(
                format!(
                    "[{}] Multimedia bundle",
                    if self.desired.bundles.multimedia {
                        "x"
                    } else {
                        " "
                    }
                ),
                "Multimedia software bundle",
            ),
            MenuItem::info(
                format!("Browser: {}", self.desired.browser.default),
                "Cycle none / Firefox / Brave / LibreWolf",
            ),
            MenuItem::info(
                format!(
                    "[{}] Filen",
                    if self.desired.integrations.filen.enable {
                        "x"
                    } else {
                        " "
                    }
                ),
                "Enable Filen integration",
            ),
            MenuItem::info(
                format!("Filen client: {}", self.desired.integrations.filen.client),
                "Cycle Desktop / CLI",
            ),
            MenuItem::info(
                format!(
                    "[{}] Filen autostart",
                    if self.desired.integrations.filen.autostart {
                        "x"
                    } else {
                        " "
                    }
                ),
                "Start Filen Desktop with the graphical session",
            ),
            MenuItem::info(
                if self.desired_dirty {
                    "Save & Apply *"
                } else {
                    "Save & Apply"
                },
                "Write desired state and rebuild the host",
            ),
        ]
    }

    fn visible_items(&self) -> Vec<MenuItem> {
        let mut items = if self.category_name() == "Configure" {
            self.configure_items()
        } else {
            self.categories
                .get(self.selected_category())
                .map(|c| c.items.clone())
                .unwrap_or_default()
        };
        if !self.search.is_empty() {
            let needle = self.search.to_ascii_lowercase();
            items.retain(|item| {
                item.name.to_ascii_lowercase().contains(&needle)
                    || item.description.to_ascii_lowercase().contains(&needle)
            });
        }
        items
    }

    fn move_selection(state: &mut ListState, len: usize, delta: isize) {
        if len == 0 {
            state.select(None);
            return;
        }
        let current = state.selected().unwrap_or(0) as isize;
        let next = (current + delta).rem_euclid(len as isize) as usize;
        state.select(Some(next));
    }

    fn activate_configure(&mut self) {
        let index = self.item_state.selected().unwrap_or(0);
        let result = match index {
            0 => self.desired.toggle_desktop("mango"),
            1 => self.desired.toggle_desktop("hyprland"),
            2 => self.desired.toggle_desktop("niri"),
            3 => {
                self.desired.shell = if self.desired.shell == "noctalia" {
                    "caelestia".into()
                } else {
                    "noctalia".into()
                };
                if self.desired.shell == "caelestia" {
                    self.desired.desktops = vec!["hyprland".into()];
                    self.desired.default_session = "hyprland".into();
                }
                self.desired.validate()
            }
            4 => {
                if let Some(pos) = self
                    .desired
                    .desktops
                    .iter()
                    .position(|d| d == &self.desired.default_session)
                {
                    self.desired.default_session =
                        self.desired.desktops[(pos + 1) % self.desired.desktops.len()].clone();
                }
                Ok(())
            }
            5 => {
                self.desired.bundles.gaming = !self.desired.bundles.gaming;
                Ok(())
            }
            6 => {
                self.desired.bundles.office = !self.desired.bundles.office;
                Ok(())
            }
            7 => {
                self.desired.bundles.development = !self.desired.bundles.development;
                Ok(())
            }
            8 => {
                self.desired.bundles.multimedia = !self.desired.bundles.multimedia;
                Ok(())
            }
            9 => {
                self.desired.browser.default = match self.desired.browser.default.as_str() {
                    "none" => "firefox",
                    "firefox" => "brave",
                    "brave" => "librewolf",
                    _ => "none",
                }
                .into();
                Ok(())
            }
            10 => {
                self.desired.integrations.filen.enable = !self.desired.integrations.filen.enable;
                Ok(())
            }
            11 => {
                self.desired.integrations.filen.client =
                    if self.desired.integrations.filen.client == "desktop" {
                        "cli".into()
                    } else {
                        "desktop".into()
                    };
                Ok(())
            }
            12 => {
                self.desired.integrations.filen.autostart =
                    !self.desired.integrations.filen.autostart;
                Ok(())
            }
            13 => {
                if let Err(error) = self.desired.save(&self.snapshot.repo, &self.snapshot.host) {
                    self.pending = Some(Command::Raw(format!(
                        "printf '%s\\n' {}",
                        shell_escape(&format!("Failed to save desired state: {error}"))
                    )));
                } else {
                    self.desired_dirty = false;
                    self.pending = Some(apply_command(&self.snapshot));
                }
                self.spawn_confirmation();
                return;
            }
            _ => Ok(()),
        };
        if result.is_ok() {
            self.desired_dirty = true;
        }
    }

    fn activate_item(&mut self) {
        if self.category_name() == "Configure" {
            self.activate_configure();
            return;
        }
        let items = self.visible_items();
        let Some(item) = self.item_state.selected().and_then(|i| items.get(i)) else {
            return;
        };
        if !matches!(item.command, Command::None) {
            self.pending = Some(item.command.clone());
            self.spawn_confirmation();
        }
    }

    fn spawn_confirmation(&mut self) {
        if self.pending.is_none() {
            return;
        }
        let visible = self.visible_items();
        let name = visible
            .get(self.item_state.selected().unwrap_or(0))
            .map(|i| i.name.as_str())
            .unwrap_or("Apply selected action");
        self.confirm = Some(Float::new(
            Box::new(ConfirmPrompt::new(&[name])),
            CONFIRM_SIZE,
            CONFIRM_SIZE,
        ));
        self.focus = Focus::Confirmation;
    }

    fn handle_confirmation(&mut self, key: &KeyEvent) {
        let Some(confirm) = self.confirm.as_mut() else {
            return;
        };
        confirm.handle_key_event(key);
        if confirm.content.is_finished() {
            match confirm.content.status {
                ConfirmStatus::Confirm => {
                    self.confirm = None;
                    if let Some(command) = self.pending.take() {
                        self.float = Some(Float::new(
                            Box::new(RunningCommand::new(&[&command])),
                            FLOAT_SIZE,
                            FLOAT_SIZE,
                        ));
                        self.focus = Focus::Floating;
                    }
                }
                ConfirmStatus::Abort => {
                    self.confirm = None;
                    self.pending = None;
                    self.focus = Focus::Items;
                }
                ConfirmStatus::None => {}
            }
        }
    }

    pub fn handle_key(&mut self, key: &KeyEvent) -> bool {
        if key.code == KeyCode::Char('c')
            && key.modifiers.contains(KeyModifiers::CONTROL)
            && self.focus != Focus::Floating
        {
            return false;
        }
        if self.focus == Focus::Floating {
            if let Some(float) = self.float.as_mut() {
                if float.handle_key_event(key) {
                    self.float = None;
                    self.focus = Focus::Items;
                    self.refresh();
                }
            }
            return true;
        }
        if self.focus == Focus::Confirmation {
            self.handle_confirmation(key);
            return true;
        }
        if self.focus == Focus::Search {
            match key.code {
                KeyCode::Esc | KeyCode::Enter => self.focus = Focus::Items,
                KeyCode::Backspace => {
                    self.search.pop();
                    self.item_state.select(Some(0));
                }
                KeyCode::Char(c) => {
                    self.search.push(c);
                    self.item_state.select(Some(0));
                }
                _ => {}
            }
            return true;
        }
        match key.code {
            KeyCode::Char('q') => return false,
            KeyCode::Char('/') => self.focus = Focus::Search,
            KeyCode::Char('t') => self.theme.next(),
            KeyCode::Char('T') => self.theme.prev(),
            KeyCode::Left | KeyCode::Char('h') => self.focus = Focus::Categories,
            KeyCode::Right | KeyCode::Char('l') if self.focus == Focus::Categories => {
                self.focus = Focus::Items
            }
            KeyCode::Up | KeyCode::Char('k') => {
                if self.focus == Focus::Categories {
                    Self::move_selection(&mut self.category_state, self.categories.len(), -1);
                    self.item_state.select(Some(0));
                } else {
                    let len = self.visible_items().len();
                    Self::move_selection(&mut self.item_state, len, -1);
                }
            }
            KeyCode::Down | KeyCode::Char('j') => {
                if self.focus == Focus::Categories {
                    Self::move_selection(&mut self.category_state, self.categories.len(), 1);
                    self.item_state.select(Some(0));
                } else {
                    let len = self.visible_items().len();
                    Self::move_selection(&mut self.item_state, len, 1);
                }
            }
            KeyCode::Enter | KeyCode::Char(' ') => {
                if self.focus == Focus::Categories {
                    self.focus = Focus::Items;
                } else {
                    self.activate_item();
                }
            }
            _ => {}
        }
        true
    }

    pub fn handle_mouse(&mut self, event: &MouseEvent) -> bool {
        if !self.mouse_enabled {
            return true;
        }
        if self.focus == Focus::Floating {
            if let Some(float) = self.float.as_mut() {
                float.handle_mouse_event(event);
            }
        }
        if self.focus == Focus::Confirmation {
            if let Some(confirm) = self.confirm.as_mut() {
                confirm.handle_mouse_event(event);
            }
        }
        true
    }

    fn refresh(&mut self) {
        if let Ok(snapshot) = nix_settings_core::snapshot() {
            self.snapshot = snapshot;
            self.categories = categories(&self.snapshot);
        }
    }

    pub fn draw(&mut self, frame: &mut Frame) {
        let area = frame.area();
        if !self.size_bypass && (area.width < MIN_WIDTH || area.height < MIN_HEIGHT) {
            frame.render_widget(Paragraph::new(format!("Terminal too small. Need at least {MIN_WIDTH}x{MIN_HEIGHT}. Use --size-bypass to override.")).centered(), area);
            return;
        }

        let vertical = Layout::vertical([Constraint::Min(10), Constraint::Length(4)]).split(area);
        let main =
            Layout::horizontal([Constraint::Length(28), Constraint::Min(40)]).split(vertical[0]);
        self.draw_sidebar(frame, main[0]);
        self.draw_content(frame, main[1]);
        self.draw_hints(frame, vertical[1]);

        if let Some(float) = self.float.as_mut() {
            float.draw(frame, area, &self.theme);
        }
        if let Some(confirm) = self.confirm.as_mut() {
            confirm.draw(frame, area, &self.theme);
        }
    }

    fn draw_sidebar(&mut self, frame: &mut Frame, area: Rect) {
        let info_height = self
            .system_info
            .as_ref()
            .map(|i| i.entries_len() as u16 + 2)
            .unwrap_or(2);
        let chunks = Layout::vertical([
            Constraint::Length(5),
            Constraint::Min(8),
            Constraint::Length(info_height),
        ])
        .split(area);
        let logo = Paragraph::new(vec![
            Line::styled(
                " NIX SETTINGS ",
                Style::default().fg(self.theme.tab_color()).bold(),
            ),
            Line::styled(
                format!(" {} · {}", self.snapshot.host, self.snapshot.commit),
                Style::default().fg(self.theme.unfocused_color()),
            ),
        ])
        .block(Block::bordered().border_set(border::PLAIN).border_style(
            Style::default().fg(if self.focus == Focus::Categories {
                self.theme.focused_color()
            } else {
                self.theme.unfocused_color()
            }),
        ));
        frame.render_widget(logo, chunks[0]);

        let rows: Vec<ListItem> = self
            .categories
            .iter()
            .map(|c| ListItem::new(format!("> {}", c.name)))
            .collect();
        let block = Block::bordered()
            .title(" NIX SETTINGS ")
            .border_set(border::PLAIN)
            .border_style(Style::default().fg(if self.focus == Focus::Categories {
                self.theme.focused_color()
            } else {
                self.theme.unfocused_color()
            }));
        let list = List::new(rows)
            .block(block)
            .highlight_style(Style::default().fg(self.theme.tab_color()).bold())
            .highlight_symbol("> ");
        frame.render_stateful_widget(list, chunks[1], &mut self.category_state);

        let info_block = Block::bordered()
            .title(" SYSTEM ")
            .border_set(border::PLAIN)
            .border_style(Style::default().fg(self.theme.unfocused_color()));
        let inner = info_block.inner(chunks[2]);
        frame.render_widget(info_block, chunks[2]);
        if let Some(info) = &self.system_info {
            frame.render_widget(
                Paragraph::new(info.render_lines(&self.theme, inner.width as usize)),
                inner,
            );
        }
    }

    fn draw_content(&mut self, frame: &mut Frame, area: Rect) {
        let chunks = Layout::vertical([Constraint::Length(3), Constraint::Min(5)]).split(area);
        let search_style = if self.focus == Focus::Search {
            self.theme.focused_color()
        } else {
            self.theme.unfocused_color()
        };
        let search = Paragraph::new(if self.search.is_empty() {
            " / Search".into()
        } else {
            format!(" / {}", self.search)
        })
        .block(
            Block::bordered()
                .title(" SEARCH ")
                .border_set(border::PLAIN)
                .border_style(Style::default().fg(search_style)),
        );
        frame.render_widget(search, chunks[0]);

        let items = self.visible_items();
        let rows: Vec<ListItem> = items
            .iter()
            .map(|item| {
                let style = match item.command {
                    Command::None => Style::default().fg(self.theme.dir_color()),
                    _ => Style::default().fg(self.theme.cmd_color()),
                };
                ListItem::new(Line::styled(item.name.clone(), style))
            })
            .collect();
        let title = format!(" {} ", self.category_name().to_ascii_uppercase());
        let list = List::new(rows)
            .block(
                Block::bordered()
                    .title(title)
                    .border_set(border::PLAIN)
                    .border_style(Style::default().fg(if self.focus == Focus::Items {
                        self.theme.focused_color()
                    } else {
                        self.theme.unfocused_color()
                    })),
            )
            .highlight_style(Style::default().fg(self.theme.focused_color()).bold())
            .highlight_symbol("> ");
        frame.render_stateful_widget(list, chunks[1], &mut self.item_state);
    }

    fn draw_hints(&self, frame: &mut Frame, area: Rect) {
        let shortcuts: Box<[Shortcut]> = shortcuts!(
            ("Quit", ["q", "CTRL-c"]),
            ("Navigate", ["j/k", "Up/Down"]),
            ("Panels", ["h/l", "Left/Right"]),
            ("Open/Toggle", ["Enter", "Space"]),
            ("Search", ["/"]),
            ("Theme", ["t", "T"]),
        );
        let lines = create_shortcut_list(shortcuts, area.width.saturating_sub(2));
        frame.render_widget(
            Paragraph::new(lines.into_vec())
                .block(Block::new().borders(Borders::TOP).title(" SHORTCUTS ")),
            area,
        );
    }
}

fn shell_escape(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}
