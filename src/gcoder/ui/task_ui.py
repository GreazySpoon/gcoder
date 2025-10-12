# src/gcoder/ui/task_ui.py

from typing import Any, Dict
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

# A single, shared console instance
console = Console()

class TaskDashboard:
    """Manages the dynamic display for a running autonomous task in the terminal."""
    def __init__(self, task: str):
        self.task = task
        self.state: Dict[str, Any] = {"original_task": task}
        self.live = Live(console=console, auto_refresh=False, vertical_overflow="visible")

    def update(self, state_delta: Dict[str, Any]):
        """Callback function to update the state and refresh the display."""
        self.state.update(state_delta)
        self.live.update(self.render(), refresh=True)

    def render(self) -> Group:
        """Renders the dashboard based on the current state."""
        panels = []
        
        plan_str = self.state.get("plan", "")
        if plan_str:
            # Handle plan being a simple string or a list of strings
            plan_list = plan_str if isinstance(plan_str, list) else [line for line in plan_str.split('\n') if line.strip()]
            
            current_index = self.state.get("current_step_index", 0)
            
            plan_items = []
            for i, step_desc in enumerate(plan_list):
                clean_step_desc = ". ".join(step_desc.split(". ")[1:]) if ". " in step_desc else step_desc
                
                if i < current_index:
                    # Completed Step
                    plan_items.append(Text(f"✅ {clean_step_desc}", style="bold green"))
                elif i == current_index:
                    # In-Progress Step - THE CORE FIX
                    spinner = Spinner("dots", style="cyan")
                    # Create a group of the spinner and text to render on the same line
                    plan_items.append(Group(spinner, Text(f" {clean_step_desc}")))
                else:
                    # Pending Step
                    plan_items.append(Text(f"⚪ {clean_step_desc}", style="dim"))
            
            panels.append(Panel(Group(*plan_items), title="[bold green]📋 Plan[/bold green]", border_style="green"))

        # Display the coordinator's last report from a specialist
        last_report = self.state.get("last_report")
        if last_report:
             panels.append(Panel(last_report, title="[bold blue]📝 Last Specialist Report[/bold blue]", border_style="blue"))

        return Group(*panels)