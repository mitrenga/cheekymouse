<?php
  $appName = 'CHEEKY MOUSE';
  $appDescription = 'Play CHEEKY MOUSE online for free in your browser. Faithful remake of the 1980 Universal arcade game with no download required.';
  $appPrefix = 'cm';
  $appNoscript =
    '<h1>CHEEKY MOUSE</h1>'.
    '<p>Cheeky Mouse is the 1980 arcade game by Universal. Mice pour out of their lair in the attic, '.
    'run down the house, chew holes through the floor and carry the cheese out of the cellar. '.
    'Armed with a hammer, you have to stop them — and keep clear of the pests that show up '.
    'after every forty mice.</p>'.
    '<p>This is a faithful remake of the arcade version that runs directly in your web browser. '.
    'There is nothing to install and nothing to download — just open the page and play. '.
    'Please enable JavaScript to start the game.</p>'.
    '<p><a href="about">More about Cheeky Mouse and this remake</a></p>';
  $appOpenGraph = [
  ];
  $appJsonLd = [
    'genre' => 'Action game',
    'isBasedOn' => [
      '@type' => 'VideoGame',
      'name' => 'Cheeky Mouse',
      'publisher' => [
        ['@type' => 'Organization', 'name' => 'Universal'],
      ],
      'datePublished' => '1980',
      'gamePlatform' => 'Arcade',
    ],
  ];
  require_once 'config/config.php';
  require_once 'app/svision/php/main.php';
