import logging
import os
import time
import json

import pwnagotchi.plugins as plugins
from pwnagotchi.ui.components import *
from pwnagotchi.ui.view import BLACK
from PIL import ImageFont
import pwnagotchi.ui.fonts as fonts
import pwnagotchi.utils as utils


class Incognito(plugins.Plugin):
    __author__ = "C0D3-5T3W"
    __version__ = "1.0.0"
    __license__ = "MIT"
    __description__ = "Incognito mode - hides all UI elements except the face which becomes a roaming pet. Compatible with tweak_view.py, also any ui modifying plugins."

    def __init__(self):
        self._agent = None
        self._start = time.time()
        self._logger = logging.getLogger(__name__)
        self._original_positions = {}
        self._original_properties = {}
        self._already_hidden = []
        self._face_element = None
        self._ui = None
        self._enabled = True

        self._pet_x = 50.0
        self._pet_y = 50.0
        self._pet_velocity_x = 1.5
        self._pet_velocity_y = 1.0
        self._pet_direction_x = 1
        self._pet_direction_y = 1
        self._screen_width = 250
        self._screen_height = 122
        self._pet_size = 15
        self._movement_enabled = True
        self._last_move_time = time.time()
        self._move_interval = 0.05

    def _save_original_state(self, ui, element_name, element):
        """Save original state of UI elements before hiding them"""
        if element_name not in self._original_positions:
            self._original_positions[element_name] = {}
            self._original_properties[element_name] = {}

            if hasattr(element, "xy"):
                self._original_positions[element_name]["xy"] = element.xy

            properties_to_save = [
                "color",
                "font",
                "text_font",
                "label_font",
                "alt_font",
                "label",
                "size",
                "width",
                "height",
                "scale",
                "font_size",
            ]
            for prop in properties_to_save:
                if hasattr(element, prop):
                    self._original_properties[element_name][prop] = getattr(
                        element, prop
                    )

            self._logger.debug(
                "Saved original state for %s: pos=%s, props=%s"
                % (
                    element_name,
                    self._original_positions[element_name],
                    self._original_properties[element_name],
                )
            )

    def _hide_element(self, ui, element_name, element):
        """Hide an element by moving it off-screen"""
        try:
            if hasattr(element, "xy"):

                element.xy = (-9999, -9999)
                self._logger.debug("Hidden element: %s" % element_name)
        except Exception as err:
            self._logger.warning(
                "Failed to hide element %s: %s" % (element_name, repr(err))
            )

    def _show_element(self, ui, element_name):
        """Restore an element to its original position"""
        try:
            if (
                element_name in self._original_positions
                and element_name in ui._state._state
            ):
                element = ui._state._state[element_name]
                if "xy" in self._original_positions[element_name]:
                    element.xy = self._original_positions[element_name]["xy"]

                for prop, value in self._original_properties[element_name].items():
                    if hasattr(element, prop):
                        setattr(element, prop, value)

                self._logger.debug(
                    "Restored element: %s to %s"
                    % (element_name, self._original_positions[element_name]["xy"])
                )
        except Exception as err:
            self._logger.warning(
                "Failed to restore element %s: %s" % (element_name, repr(err))
            )

    def _get_screen_dimensions(self, ui):
        """Get the actual screen dimensions with fallbacks"""
        try:

            width = None
            height = None

            if hasattr(ui, "width") and callable(ui.width):
                width = ui.width()
            if hasattr(ui, "height") and callable(ui.height):
                height = ui.height()

            if not width and hasattr(ui, "_width"):
                width = ui._width
            if not height and hasattr(ui, "_height"):
                height = ui._height

            if not width or not height:
                try:

                    if hasattr(ui, "_config") and "ui" in ui._config:
                        ui_config = ui._config["ui"]
                        if "display" in ui_config:
                            display_config = ui_config["display"]
                            if "width" in display_config:
                                width = display_config["width"]
                            if "height" in display_config:
                                height = display_config["height"]
                except:
                    pass

            if not width:
                width = 250
            if not height:
                height = 122

            common_sizes = {
                (250, 122): 'Waveshare 2.13"',
                (128, 64): "OLED 128x64",
                (128, 32): "OLED 128x32",
                (296, 128): 'Waveshare 2.9"',
                (400, 300): 'Waveshare 4.2"',
                (212, 104): 'Waveshare 2.13" v2',
            }

            display_type = common_sizes.get((width, height), "Unknown")
            self._logger.info(
                "Detected display: %dx%d (%s)" % (width, height, display_type)
            )

            return width, height

        except Exception as err:
            self._logger.warning(
                "Could not determine screen dimensions: %s" % repr(err)
            )
            return 250, 122

    def _find_face_element(self, ui):
        """Find the face element in the UI state with improved detection"""
        state = ui._state._state

        face_candidates = [
            "face",
            "Face",
            "FACE",
            "status",
            "Status",
            "STATUS",
            "mood",
            "Mood",
            "MOOD",
            "emoji",
            "Emoji",
            "EMOJI",
            "expression",
            "Expression",
        ]

        for candidate in face_candidates:
            if candidate in state:
                self._logger.info("Found face element (exact match): %s" % candidate)
                return candidate

        face_element = None
        for element_name, element in state.items():
            element_name_lower = element_name.lower()

            face_keywords = ["face", "status", "mood", "emoji", "expression", "smile"]
            if any(keyword in element_name_lower for keyword in face_keywords):
                self._logger.info(
                    "Found face element (keyword match): %s" % element_name
                )
                face_element = element_name
                break

            if hasattr(element, "draw"):

                if hasattr(element, "value") or hasattr(element, "text"):
                    face_element = element_name
                    self._logger.info(
                        "Found potential face element (drawable): %s" % element_name
                    )

        if face_element:
            return face_element

        for element_name, element in state.items():
            if hasattr(element, "draw"):
                self._logger.warning("Using fallback face element: %s" % element_name)
                return element_name

        self._logger.warning("Could not find any face element!")
        return None

    def _setup_pet_face(self, ui, face_element_name):
        """Setup the face as a small pet and initialize movement"""
        try:
            if face_element_name and face_element_name in ui._state._state:
                face_element = ui._state._state[face_element_name]

                self._screen_width, self._screen_height = self._get_screen_dimensions(
                    ui
                )

                if hasattr(face_element, "font"):
                    pet_fonts = [fonts.Small, fonts.Medium, fonts.BoldSmall]

                    for font in pet_fonts:
                        try:
                            face_element.font = font
                            self._logger.info("Applied pet font: %s" % str(font))
                            break
                        except Exception as e:
                            continue

                if hasattr(face_element, "text_font"):
                    try:
                        face_element.text_font = fonts.Small
                    except:
                        pass

                self._pet_x = float(self._screen_width // 2)
                self._pet_y = float(self._screen_height // 2)

                if hasattr(face_element, "xy"):
                    face_element.xy = (int(self._pet_x), int(self._pet_y))
                    self._logger.info(
                        "Set initial pet position: (%.1f, %.1f)"
                        % (self._pet_x, self._pet_y)
                    )
                else:
                    self._logger.warning("Face element has no 'xy' attribute!")

                import random

                self._pet_direction_x = random.choice([-1, 1])
                self._pet_direction_y = random.choice([-1, 1])
                self._pet_velocity_x = random.uniform(0.8, 2.0)
                self._pet_velocity_y = random.uniform(0.5, 1.5)

                self._movement_enabled = True
                self._last_move_time = time.time()

                self._logger.info(
                    "Setup pet face '%s' at (%.1f, %.1f) on %dx%d screen, velocity=(%.2f,%.2f), direction=(%d,%d)"
                    % (
                        face_element_name,
                        self._pet_x,
                        self._pet_y,
                        self._screen_width,
                        self._screen_height,
                        self._pet_velocity_x,
                        self._pet_velocity_y,
                        self._pet_direction_x,
                        self._pet_direction_y,
                    )
                )
            else:
                self._logger.error(
                    "Face element '%s' not found in UI state!" % face_element_name
                )
        except Exception as err:
            self._logger.warning("Failed to setup pet face: %s" % repr(err))

    def _move_pet(self, ui):
        """Move the pet face around the screen with smooth, accurate border collision"""
        try:
            current_time = time.time()

            if current_time - self._last_move_time < self._move_interval:
                return

            if not self._movement_enabled:
                self._logger.info("Movement disabled - not moving pet")
                return

            if not self._face_element:
                self._logger.info("No face element found - cannot move pet")
                return

            if self._face_element not in ui._state._state:
                self._logger.info(
                    "Face element '%s' not in UI state" % self._face_element
                )
                return

            face_element = ui._state._state[self._face_element]

            old_x, old_y = self._pet_x, self._pet_y

            next_x = self._pet_x + (self._pet_velocity_x * self._pet_direction_x)
            next_y = self._pet_y + (self._pet_velocity_y * self._pet_direction_y)

            margin = self._pet_size

            if next_x <= margin:
                next_x = margin
                self._pet_direction_x = 1
                import random

                self._pet_velocity_x = random.uniform(0.8, 2.0)
                self._logger.info("Pet hit left boundary, bouncing right")

            elif next_x >= (self._screen_width - margin):
                next_x = self._screen_width - margin
                self._pet_direction_x = -1
                import random

                self._pet_velocity_x = random.uniform(0.8, 2.0)
                self._logger.info("Pet hit right boundary, bouncing left")

            if next_y <= margin:
                next_y = margin
                self._pet_direction_y = 1
                import random

                self._pet_velocity_y = random.uniform(0.5, 1.5)
                self._logger.info("Pet hit top boundary, bouncing down")

            elif next_y >= (self._screen_height - margin):
                next_y = self._screen_height - margin
                self._pet_direction_y = -1
                import random

                self._pet_velocity_y = random.uniform(0.5, 1.5)
                self._logger.info("Pet hit bottom boundary, bouncing up")

            self._pet_x = next_x
            self._pet_y = next_y

            if hasattr(face_element, "xy"):
                face_element.xy = (int(self._pet_x), int(self._pet_y))
                self._logger.info(
                    "Pet moved smoothly from (%.1f,%.1f) to (%.1f,%.1f)"
                    % (old_x, old_y, self._pet_x, self._pet_y)
                )
            else:
                self._logger.warning(
                    "Face element has no 'xy' attribute - cannot move!"
                )

            self._last_move_time = current_time

            import random

            if random.random() < 0.03:

                velocity_change = random.uniform(-0.2, 0.2)
                self._pet_velocity_x = max(
                    0.5, min(2.5, self._pet_velocity_x + velocity_change)
                )
                self._pet_velocity_y = max(
                    0.3, min(2.0, self._pet_velocity_y + velocity_change)
                )
                self._logger.info(
                    "Pet velocity adjusted for organic movement: (%.2f,%.2f)"
                    % (self._pet_velocity_x, self._pet_velocity_y)
                )

            if random.random() < 0.01:
                self._pet_direction_x = random.choice([-1, 1])
                self._pet_direction_y = random.choice([-1, 1])
                self._pet_velocity_x = random.uniform(0.8, 2.0)
                self._pet_velocity_y = random.uniform(0.5, 1.5)
                self._logger.info(
                    "Pet randomly changed direction: dir=(%d,%d), vel=(%.2f,%.2f)"
                    % (
                        self._pet_direction_x,
                        self._pet_direction_y,
                        self._pet_velocity_x,
                        self._pet_velocity_y,
                    )
                )

        except Exception as err:
            self._logger.error("Failed to move pet: %s" % repr(err))

    def _pause_pet_movement(self):
        """Pause pet movement"""
        self._movement_enabled = False

    def _resume_pet_movement(self):
        """Resume pet movement"""
        self._movement_enabled = True

    def _set_pet_speed(self, speed_multiplier=1.0):
        """Set pet movement speed (1.0 = normal, 2.0 = double speed, 0.5 = half speed)"""
        base_interval = 0.05
        self._move_interval = base_interval / speed_multiplier

    def _apply_incognito_mode(self, ui):
        """Apply incognito mode by hiding all elements except face"""
        if not self._enabled:
            return

        try:
            state = ui._state._state

            face_element_name = self._find_face_element(ui)

            for element_name, element in state.items():
                if element_name != face_element_name:

                    self._save_original_state(ui, element_name, element)

                    self._hide_element(ui, element_name, element)

                    if element_name not in self._already_hidden:
                        self._already_hidden.append(element_name)

            if face_element_name:
                self._save_original_state(
                    ui, face_element_name, state[face_element_name]
                )
                self._setup_pet_face(ui, face_element_name)
                self._face_element = face_element_name

            self._logger.info(
                "Incognito mode applied - showing roaming pet face: %s"
                % face_element_name
            )

        except Exception as err:
            self._logger.warning("Failed to apply incognito mode: %s" % repr(err))

    def _restore_normal_mode(self, ui):
        """Restore all UI elements to their original positions"""
        try:

            for element_name in self._already_hidden:
                self._show_element(ui, element_name)

            if self._face_element:
                self._show_element(ui, self._face_element)

            self._already_hidden.clear()
            self._logger.info("Restored normal UI mode")

        except Exception as err:
            self._logger.warning("Failed to restore normal mode: %s" % repr(err))

    def toggle_mode(self):
        """Toggle between incognito pet mode and normal mode"""
        self._enabled = not self._enabled
        if self._ui:
            if self._enabled:
                self._apply_incognito_mode(self._ui)
                self._logger.info("Incognito pet mode enabled")
            else:
                self._restore_normal_mode(self._ui)
                self._logger.info("Incognito pet mode disabled")

    def on_loaded(self):
        self._start = time.time()
        self._logger.info("Incognito plugin loaded")

    def on_ready(self, agent):
        self._agent = agent
        self._logger.info("Incognito plugin ready")

    def on_ui_setup(self, ui):
        """Called when UI is being set up"""
        self._ui = ui

        if "enabled" in self.options:
            self._enabled = self.options["enabled"]

        if self._enabled:
            self._apply_incognito_mode(ui)

            self._logger.info("Testing pet movement after setup...")
            if self._face_element:
                for i in range(3):
                    result = self._force_move_pet_now(ui)
                    self._logger.info(
                        "Setup test move %d: success=%s, position=(%d,%d)"
                        % (i + 1, result, self._pet_x, self._pet_y)
                    )

        self._logger.info(
            "Incognito UI setup complete - pet mode (enabled: %s)" % self._enabled
        )

    def on_ui_update(self, ui):
        """Called on UI updates - maintain incognito mode and move the pet"""
        if self._enabled:

            self._move_pet(ui)

            state = ui._state._state
            for element_name, element in state.items():
                if (
                    element_name != self._face_element
                    and element_name not in self._already_hidden
                    and element_name not in self._original_positions
                ):

                    self._save_original_state(ui, element_name, element)
                    self._hide_element(ui, element_name, element)
                    self._already_hidden.append(element_name)

    def on_epoch(self, agent, epoch, epoch_data):
        """Called on each epoch - also try to move pet here for more frequent updates"""
        if self._enabled and self._ui:
            self._move_pet(self._ui)

    def on_peer_detected(self, agent, peer):
        """Called when peer detected - move pet"""
        if self._enabled and self._ui:
            self._move_pet(self._ui)

    def on_handshake(self, agent, filename, access_point, client_station):
        """Called on handshake - move pet"""
        if self._enabled and self._ui:
            self._move_pet(self._ui)

    def on_log(self, agent, entry):
        """Called on every log message - move pet for constant movement"""
        if self._enabled and self._ui:
            self._force_move_pet_now(self._ui)

    def on_wifi_update(self, agent, access_points):
        """Called on wifi updates - move pet"""
        if self._enabled and self._ui:
            self._force_move_pet_now(self._ui)

    def on_unload(self, ui):
        """Called when plugin is unloaded - restore normal mode"""
        try:
            self._restore_normal_mode(ui)
            self._logger.info("Incognito plugin unloaded - UI restored")
        except Exception as err:
            self._logger.warning("Error during unload: %s" % repr(err))

    def on_unloaded(self):
        """Final cleanup"""
        self._logger.info("Incognito plugin unloaded completely")

    def get_hidden_elements(self):
        """Return list of currently hidden elements for tweak_view compatibility"""
        return self._already_hidden.copy()

    def get_face_element(self):
        """Return the face element name for tweak_view compatibility"""
        return self._face_element

    def is_incognito_enabled(self):
        """Check if incognito mode is currently enabled"""
        return self._enabled

    def get_original_positions(self):
        """Get original positions for tweak_view compatibility"""
        return self._original_positions.copy()

    def get_pet_position(self):
        """Get current pet position"""
        return (self._pet_x, self._pet_y)

    def set_pet_position(self, x, y):
        """Manually set pet position"""
        self._pet_x = max(
            self._pet_size, min(float(x), self._screen_width - self._pet_size)
        )
        self._pet_y = max(
            self._pet_size, min(float(y), self._screen_height - self._pet_size)
        )

        if (
            self._ui
            and self._face_element
            and self._face_element in self._ui._state._state
        ):
            face_element = self._ui._state._state[self._face_element]
            if hasattr(face_element, "xy"):
                face_element.xy = (int(self._pet_x), int(self._pet_y))

    def pause_pet(self):
        """Pause pet movement"""
        self._pause_pet_movement()
        self._logger.info("Pet movement paused")

    def resume_pet(self):
        """Resume pet movement"""
        self._resume_pet_movement()
        self._logger.info("Pet movement resumed")

    def set_pet_speed(self, speed=1.0):
        """Set pet movement speed (1.0 = normal, 2.0 = double, 0.5 = half)"""
        self._set_pet_speed(speed)
        self._logger.info("Pet speed set to %.1fx" % speed)

    def get_pet_info(self):
        """Get pet status information"""
        return {
            "position": (self._pet_x, self._pet_y),
            "velocity": (self._pet_velocity_x, self._pet_velocity_y),
            "direction": (self._pet_direction_x, self._pet_direction_y),
            "screen_size": (self._screen_width, self._screen_height),
            "movement_enabled": self._movement_enabled,
            "move_interval": self._move_interval,
            "face_element": self._face_element,
            "time_since_last_move": time.time() - self._last_move_time,
        }

    def force_pet_move(self):
        """Force the pet to move immediately (for testing)"""
        if self._ui and self._enabled:
            self._last_move_time = 0
            self._move_pet(self._ui)
            self._logger.info("Forced pet movement")
            return True
        return False

    def _force_move_pet_now(self, ui):
        """Immediately move pet without any timing checks using smooth movement"""
        try:
            if not self._movement_enabled:
                self._logger.info("FORCE: Movement disabled - enabling it")
                self._movement_enabled = True

            if not self._face_element:
                self._logger.error("FORCE: No face element found")
                return False

            if self._face_element not in ui._state._state:
                self._logger.error(
                    "FORCE: Face element '%s' not in UI state" % self._face_element
                )
                return False

            face_element = ui._state._state[self._face_element]

            old_x, old_y = self._pet_x, self._pet_y

            next_x = self._pet_x + (self._pet_velocity_x * self._pet_direction_x)
            next_y = self._pet_y + (self._pet_velocity_y * self._pet_direction_y)

            margin = self._pet_size

            if next_x <= margin:
                next_x = margin
                self._pet_direction_x = 1
            elif next_x >= (self._screen_width - margin):
                next_x = self._screen_width - margin
                self._pet_direction_x = -1

            if next_y <= margin:
                next_y = margin
                self._pet_direction_y = 1
            elif next_y >= (self._screen_height - margin):
                next_y = self._screen_height - margin
                self._pet_direction_y = -1

            self._pet_x = next_x
            self._pet_y = next_y

            if hasattr(face_element, "xy"):
                face_element.xy = (int(self._pet_x), int(self._pet_y))
                self._logger.info(
                    "FORCE MOVED: Pet from (%.1f,%.1f) to (%.1f,%.1f)"
                    % (old_x, old_y, self._pet_x, self._pet_y)
                )
                return True
            else:
                self._logger.error("FORCE: Face element has no 'xy' attribute!")
                return False

        except Exception as err:
            self._logger.error("FORCE MOVE failed: %s" % repr(err))
            return False

    def test_pet_movement(self):
        """Test pet movement by moving it 10 times quickly"""
        if not self._ui or not self._enabled:
            self._logger.warning("Cannot test - UI not available or plugin disabled")
            return False

        self._logger.info("Starting pet movement test...")

        for i in range(10):
            result = self._force_move_pet_now(self._ui)
            self._logger.info(
                "Test move %d: success=%s, pet at (%d, %d)"
                % (i + 1, result, self._pet_x, self._pet_y)
            )

        self._logger.info("Pet movement test completed")
        return True
