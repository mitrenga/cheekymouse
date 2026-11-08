<?php

require_once 'app/svision/php/abstractAboutPage.php';

/**
 * The /about page: the story of the original Cheeky Mouse and this remake.
 * M1 placeholder text; the final content comes with M6.
 */
class AboutPage extends AbstractAboutPage {

  protected function aboutData() {
    return [
      'sections' => [
        [
          'heading' => 'The original game (1980)',
          'html' =>
            '<p>Cheeky Mouse was released by Universal in 1980 for both upright and cocktail cabinets. '.
            'It is played on a vertically oriented monitor: the mice live in a lair at the top of the '.
            'screen and come out through its holes one after another, run down to the floor, chew a hole '.
            'through it and carry the cheese out of the cellar below. You move a man with a hammer left '.
            'and right along the floor and swing at them — a mouse on its way down is worth 20 to 100 '.
            'points, one already carrying cheese twice that. Every screen holds 32 mice; the more screens '.
            'you clear the faster they get, the more of them come at once and the more windows appear for '.
            'them to hide behind. After every forty mice killed a mystery pest turns up and walks straight '.
            'at the man — one touch and he falls. So does losing all eight pieces of cheese.</p>',
        ],
        [
          'heading' => 'This remake',
          'html' =>
            '<p>This is a faithful remake of the Universal arcade version: the game logic is being '.
            'rewritten for the web browser, not emulated, from the original manual, the MAME hardware '.
            'driver and the program ROM. Even the frame rate is the original 58.64 Hz rather than a '.
            'convenient 60. It runs directly in your browser — nothing to install, nothing to download. '.
            'Keyboard, touch controls and gamepads are supported.</p>'.$this->installNote(),
        ],
        [
          'heading' => 'Other games',
          'html' =>
            '<p>This remake is one of a growing collection of classic games from the 8-bit and 16-bit era '.
            '— ZX Spectrum, Commodore 64, arcade and more — rebuilt faithfully on the same library and '.
            'playable in your browser, free of charge. Browse the whole collection at '.
            '<a href="https://retrogames.free/" target="_blank" rel="noopener">retrogames.free</a>.</p>',
        ],
      ],
      'links' => [
        ['label' => 'Cheeky Mouse at the Museum of the Game', 'url' => 'https://www.arcade-museum.com/Videogame/cheeky-mouse'],
        ['label' => 'Cheeky Mouse at PixelatedArcade', 'url' => 'https://pixelatedarcade.com/games/cheeky-mouse'],
      ],
      'footer' =>
        '<p>An unofficial fan remake. The original game and its artwork belong to their authors (Universal). '.
        'The remake\'s source code is licensed under <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noopener">CC BY-NC-SA 4.0</a>.</p>',
    ];
  } // aboutData

} // AboutPage
