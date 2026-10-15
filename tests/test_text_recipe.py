"""Text recipes: fitted from an accepted image, drawn onto the next one."""

import unittest

from tests.probe import Probe

# The recipe tool imports the engine's `util` package, which would clash with
# the fakes other tests install, so it runs in its own interpreter.
journey = Probe("text_recipe.py")


class TextRecipeTests(unittest.TestCase):
    def test_fitted_recipe_draws_the_next_image_and_the_editor_draws_its_effects(self):
        returncode, output = journey.result()
        self.assertEqual(returncode, 0, output)
