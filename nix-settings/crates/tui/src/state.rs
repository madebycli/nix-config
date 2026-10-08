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

#[derive(Clone, Copy)]
enum Bundle {
    Gaming,
    Office,
    Development,
    Multimedia,
}

#[derive(Clone, Copy)]
enum ConfigAction {
    Desktop(&'static str),
    Shell,
    DefaultSession,
    Bundle(Bundle),
    Browser,
    FilenEnable,
    FilenClient,
    FilenAutostart,
    Apply,
}

#[derive(Clone)]
struct Entry {
    item: MenuItem,
    action: Option<ConfigAction>,
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
    notice: Option<String>,
    quit_armed: bool,
    overview: String,
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
            notice: None,
            quit_armed: false,
            overview: nix_settings_core::report::status_text(),
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

    fn configure_entries(&self) -> Vec<Entry> {
        let d = &self.desired;
        let enabled = |name: &str| d.desktops.iter().any(|x| x == name);
        let check = |on: bool| if on { "[x]" } else { "[ ]" };
        let entry = |action: ConfigAction, name: String, description: &str| Entry {
            item: MenuItem::info(name, description),
            action: Some(action),
        };
        vec![
            entry(ConfigAction::Desktop("mango"), format!("{} Mango", check(enabled("mango"))), "Toggle the Mango compositor. At least one compositor must stay enabled."),
            entry(ConfigAction::Desktop("hyprland"), format!("{} Hyprland", check(enabled("hyprland"))), "Toggle the Hyprland compositor."),
            entry(ConfigAction::Desktop("niri"), format!("{} Niri", check(enabled("niri"))), "Toggle the Niri compositor."),
            entry(ConfigAction::Shell, format!("Shell: {}", d.shell), "Cycle Noctalia / Caelestia. Caelestia requires the Hyprland-only configuration and switches to it."),
            entry(ConfigAction::DefaultSession, format!("Default session: {}", d.default_session), "Cycle through the enabled compositors."),
            entry(ConfigAction::Bundle(Bundle::Gaming), format!("{} Gaming bundle", check(d.bundles.gaming)), "Steam, GameMode and MangoHud."),
            entry(ConfigAction::Bundle(Bundle::Office), format!("{} Office bundle", check(d.bundles.office)), "LibreOffice."),
            entry(ConfigAction::Bundle(Bundle::Development), format!("{} Development bundle", check(d.bundles.development)), "git, gcc, make, python3 and nodejs."),
            entry(ConfigAction::Bundle(Bundle::Multimedia), format!("{} Multimedia bundle", check(d.bundles.multimedia)), "ffmpeg and mpv."),
            entry(ConfigAction::Browser, format!("Browser: {}", d.browser.default), "Cycle none / Firefox / Brave / LibreWolf."),
            entry(ConfigAction::FilenEnable, format!("{} Filen", check(d.integrations.filen.enable)), "Install the Filen client."),
            entry(ConfigAction::FilenClient, format!("Filen client: {}", d.integrations.filen.client), "Cycle Desktop / CLI."),
            entry(ConfigAction::FilenAutostart, format!("{} Filen autostart", check(d.integrations.filen.autostart)), "Start Filen Desktop with the graphical session (Desktop client only)."),
            entry(
                ConfigAction::Apply,
                if self.desired_dirty { "Save & Apply *".into() } else { "Save & Apply".into() },
                "Write state/<host>.json and run nixos-rebuild switch for this host.",
            ),
        ]
    }

    fn visible_entries(&self) -> Vec<Entry> {
        let mut entries = if self.category_name() == "Configure" {
            self.configure_entries()
        } else {
            self.categories
                .get(self.selected_category())
                .map(|c| {
                    c.items
                        .iter()
                        .cloned()
                        .map(|item| Entry { item, action: None })
                        .collect()
                })
                .unwrap_or_default()
        };
        if !self.search.is_empty() {
            let needle = self.search.to_ascii_lowercase();
            entries.retain(|e| {
                e.item.name.to_ascii_lowercase().contains(&needle)
                    || e.item.description.to_ascii_lowercase().contains(&needle)
            });
        }
        entries
    }

    fn selected_entry(&self) -> Option<Entry> {
        let index = self.item_state.selected()?;
        self.visible_entries().into_iter().nth(index)
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

    fn apply_config(&mut self, action: ConfigAction) {
        let d = &mut self.desired;
        let result = match action {
            ConfigAction::Desktop(name) => d.toggle_desktop(name),
            ConfigAction::Shell => {
                d.shell = if d.shell == "noctalia" { "caelestia" } else { "noctalia" }.into();
                if d.shell == "caelestia" {
                    d.desktops = vec!["hyprland".into()];
                    d.default_session = "hyprland".into();
                }
                d.validate()
            }
            ConfigAction::DefaultSession => {
                if let Some(pos) = d.desktops.iter().position(|x| x == &d.default_session) {
                    d.default_session = d.desktops[(pos + 1) % d.desktops.len()].clone();
                }
                Ok(())
            }
            ConfigAction::Bundle(bundle) => {
                let flag = match bundle {
                    Bundle::Gaming => &mut d.bundles.gaming,
                    Bundle::Office => &mut d.bundles.office,
                    Bundle::Development => &mut d.bundles.development,
                    Bundle::Multimedia => &mut d.bundles.multimedia,
                };
                *flag = !*flag;
                Ok(())
            }
            ConfigAction::Browser => {
                d.browser.default = match d.browser.default.as_str() {
                    "none" => "firefox",
                    "firefox" => "brave",
                    "brave" => "librewolf",
                    _ => "none",
                }
                .into();
                Ok(())
            }
            ConfigAction::FilenEnable => {
                d.integrations.filen.enable = !d.integrations.filen.enable;
                Ok(())
            }
            ConfigAction::FilenClient => {
                let filen = &mut d.integrations.filen;
                filen.client = if filen.client == "desktop" { "cli" } else { "desktop" }.into();
                if filen.client == "cli" {
                    filen.autostart = false;
                }
                Ok(())
            }
            ConfigAction::FilenAutostart => {
                let filen = &mut d.integrations.filen;
                if filen.client == "cli" {
                    Err(anyhow::anyhow!("Filen CLI cannot autostart; switch to the Desktop client"))
                } else {
                    filen.autostart = !filen.autostart;
                    Ok(())
                }
            }
            ConfigAction::Apply => {
                match self.desired.save(&self.snapshot.repo, &self.snapshot.host) {
                    Ok(()) => {
                        self.desired_dirty = false;
                        self.pending = Some(apply_command(&self.snapshot));
                        self.spawn_confirmation("Save & Apply");
                    }
                    Err(error) => self.notice = Some(format!("Cannot save: {error}")),
                }
                return;
            }
        };
        match result {
            Ok(()) => {
                self.desired_dirty = true;
                self.notice = None;
            }
            Err(error) => {
                // validation failures leave the state half-edited; reload from disk
                self.notice = Some(error.to_string());
                if let Ok(saved) = DesiredState::load(&self.snapshot.repo, &self.snapshot.host) {
                    if !self.desired_dirty {
                        self.desired = saved;
                    }
                }
            }
        }
    }

    fn run_command(&mut self, command: Command) {
        self.float = Some(Float::new(
            Box::new(RunningCommand::new(&[&command])),
            FLOAT_SIZE,
            FLOAT_SIZE,
        ));
        self.focus = Focus::Floating;
    }

    fn activate_item(&mut self) {
        let Some(entry) = self.selected_entry() else {
            return;
        };
        if let Some(action) = entry.action {
            self.apply_config(action);
            return;
        }
        if matches!(entry.item.command, Command::None) {
            return;
        }
        if entry.item.confirm {
            self.pending = Some(entry.item.command.clone());
            self.spawn_confirmation(&entry.item.name);
        } else {
            self.run_command(entry.item.command.clone());
        }
    }

    fn spawn_confirmation(&mut self, name: &str) {
        if self.pending.is_none() {
            return;
        }
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
                        self.run_command(command);
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
        if !matches!(key.code, KeyCode::Char('q')) {
            self.quit_armed = false;
        }
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
            KeyCode::Char('q') => {
                if self.desired_dirty && !self.quit_armed {
                    self.quit_armed = true;
                    self.notice = Some("Unsaved changes. Press q again to discard them and quit.".into());
                    return true;
                }
                return false;
            }
            KeyCode::Char('r') => {
                self.refresh();
                self.notice = Some("Refreshed.".into());
            }
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
                    let len = self.visible_entries().len();
                    Self::move_selection(&mut self.item_state, len, -1);
                }
            }
            KeyCode::Down | KeyCode::Char('j') => {
                if self.focus == Focus::Categories {
                    Self::move_selection(&mut self.category_state, self.categories.len(), 1);
                    self.item_state.select(Some(0));
                } else {
                    let len = self.visible_entries().len();
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
        self.overview = nix_settings_core::report::status_text();
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
            .map(|c| {
                let dirty = c.name == "Configure" && self.desired_dirty;
                ListItem::new(format!("{}{}", c.name, if dirty { " *" } else { "" }))
            })
            .collect();
        let block = Block::bordered()
            .title(" CATEGORIES ")
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
        let overview = self.category_name() == "Overview" && self.search.is_empty();
        let chunks = Layout::vertical([
            Constraint::Length(3),
            Constraint::Min(5),
            Constraint::Length(4),
        ])
        .split(area);
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

        let border_color = if self.focus == Focus::Items {
            self.theme.focused_color()
        } else {
            self.theme.unfocused_color()
        };
        if overview {
            frame.render_widget(
                Paragraph::new(self.overview.clone()).block(
                    Block::bordered()
                        .title(" OVERVIEW ")
                        .border_set(border::PLAIN)
                        .border_style(Style::default().fg(border_color)),
                ),
                chunks[1],
            );
            self.draw_detail(frame, chunks[2], None);
            return;
        }

        let entries = self.visible_entries();
        let rows: Vec<ListItem> = entries
            .iter()
            .map(|entry| {
                let style = match (&entry.action, &entry.item.command) {
                    (Some(ConfigAction::Apply), _) => Style::default().fg(self.theme.cmd_color()).bold(),
                    (Some(_), _) => Style::default().fg(self.theme.dir_color()),
                    (None, Command::None) => Style::default().fg(self.theme.unfocused_color()),
                    _ => Style::default().fg(self.theme.cmd_color()),
                };
                ListItem::new(Line::styled(entry.item.name.clone(), style))
            })
            .collect();
        let title = format!(" {} ", self.category_name().to_ascii_uppercase());
        let list = List::new(rows)
            .block(
                Block::bordered()
                    .title(title)
                    .border_set(border::PLAIN)
                    .border_style(Style::default().fg(border_color)),
            )
            .highlight_style(Style::default().fg(self.theme.focused_color()).bold())
            .highlight_symbol("> ");
        frame.render_stateful_widget(list, chunks[1], &mut self.item_state);
        let selected = self.selected_entry();
        self.draw_detail(frame, chunks[2], selected.as_ref());
    }

    fn draw_detail(&self, frame: &mut Frame, area: Rect, entry: Option<&Entry>) {
        let (text, color) = if let Some(notice) = &self.notice {
            (notice.clone(), self.theme.fail_color())
        } else if let Some(entry) = entry {
            let mut text = entry.item.description.clone();
            if entry.item.confirm && entry.action.is_none() && !matches!(entry.item.command, Command::None) {
                text.push_str("  (asks for confirmation)");
            }
            (text, self.theme.unfocused_color())
        } else {
            ("Press r to refresh · h/l switch panels · / searches the current page".into(), self.theme.unfocused_color())
        };
        frame.render_widget(
            Paragraph::new(text)
                .wrap(ratatui::widgets::Wrap { trim: true })
                .style(Style::default().fg(color))
                .block(Block::bordered().title(" DETAILS ").border_set(border::PLAIN)
                    .border_style(Style::default().fg(self.theme.unfocused_color()))),
            area,
        );
    }

    fn draw_hints(&self, frame: &mut Frame, area: Rect) {
        let shortcuts: Box<[Shortcut]> = shortcuts!(
            ("Quit", ["q", "CTRL-c"]),
            ("Navigate", ["j/k", "Up/Down"]),
            ("Panels", ["h/l", "Left/Right"]),
            ("Open/Toggle", ["Enter", "Space"]),
            ("Search", ["/"]),
            ("Refresh", ["r"]),
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
