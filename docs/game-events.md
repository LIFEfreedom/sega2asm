# Сценарии событий этапов

СГЕНЕРИРОВАНО `tools/stagescript.py` (`make stages`) — правки
затираются, меняйте инструмент.

Главный цикл `$01631C` сразу после приращения `GameTick` зовёт
`RunStageFrameHook` `$02D090`. Тот берёт номер этапа из байта `+$3`
описания миссии и прыгает по самоотносительной таблице
`table_stageframe` `$02D0B8` — 256 записей. Соседняя
`RunStageStartHook` `$02CE68` делает то же один раз при входе на
карту, по таблице `table_stagestart` `$02CE90`.

Сценарии формульны: задать пару порогов в `d6`/`d7` и позвать общую
процедуру, либо сверить `GameTick` с точным числом и что-то
сделать — сменить музыку, подсыпать юнитов, включить отсчёт.
**`d7` — тик, на котором событие начинается, `d6` — период
повторения**; счётчик живёт в `$FFE0BC`. При 60 кадрах в секунду
`$0708` это полминуты, `$2A30` — три минуты.

Из 256 этапов на собственный сценарий указывают 175, остальные ведут
на общую заглушку `$02E8FA`.

Из них непустых — 80; прочие это один `rts`.

| этап | миссии | сценарий | что делает |
|---|---|---|---|
| 2 | гл.1 м.5 | `$02D2BC` | старт на тике $0708; повтор каждые $0384; зовёт StageSpreadType25Tick |
| 3 | гл.1 м.7 | `$02D2CA` | старт на тике $1C20; повтор каждые $D2F0; зовёт StageConvertAll14Once |
| 4 | гл.1 м.9 | `$02D2D8` | старт на тике $189C; повтор каждые $012C; на тике 6300; на тике 6450; музыка 19 = банк 3 песня $87; зовёт PlaySound, StageSpreadRandomTypeTick, LoadPlacement |
| 5 | гл.1 м.10 | `$02D32C` | старт на тике $0E10; повтор каждые $0078; зовёт StageSeedType25Tick |
| 6 | гл.1 м.37 | `$02D9FA` | на тике 9015; на тике 9030; на тике 9045; на тике 9000; музыка 19 = банк 3 песня $87; зовёт ScrollCursorToTarget, SetupFadeToPalette60, StepFadeAndUploadRow3, PlaySound |
| 7 | гл.1 м.13 | `$02D33A` | старт на тике $2328; повтор каждые $0708; зовёт StageShudderTick |
| 9 | гл.1 м.22 | `$02D34A` | старт на тике $2328; повтор каждые $00FA; зовёт TickLavaEruption |
| 10 | гл.1 м.38 | `$02D358` | на тике 5385; на тике 5401; на тике 5460; на тике 5400; музыка 105 = банк 4 песня $85; зовёт PlaySound, ScrollCursorToTarget, LoadPlacement |
| 11 | гл.1 м.19 | `$02D484` | старт на тике $2328; повтор каждые $0708; зовёт StageConvertInner14Tick |
| 12 | гл.1 м.33 | `$02D492` | зовёт FindUnitFromRandomStart, loc_01F410, ScrollToClampedCell, LoadStagePalette |
| 13 | гл.1 м.26 | `$02D534` | старт на тике $2A30; на тике 10800; музыка 101 = банк 4 песня $8D; зовёт PlaySound, StageSoundLoopTick |
| 14 | гл.1 м.31 | `$02D560` | старт на тике $6978; повтор каждые $0003; зовёт StagePoisonTick |
| 16 | гл.1 м.25 | `$02D588` | старт на тике $4650; повтор каждые $0258; на тике 18000; музыка 59 = банк 3 песня $86; зовёт PlaySound, StageConvertWaveTick |
| 17 | гл.1 м.36 | `$02D5B8` | старт на тике $19C8; повтор каждые $005A; на тике 300; на тике 4200; музыка 67 = банк 3 песня $85; зовёт FindUnitFromRandomStart, loc_01F410, ScrollToClampedCell, PlaySound |
| 19 | гл.1 м.43 | `$02D652` | старт на тике $AFC8; на тике 45000; музыка 101 = банк 4 песня $8D; зовёт PlaySound, StageSoundLoopTick |
| 20 | гл.1 м.45 | `$02D67E` | зовёт StageSpecies18MarchTick |
| 23 | гл.1 м.4 | `$02D688` | старт на тике $2328; повтор каждые $0E10; зовёт StageSpreadWideTick |
| 24 | гл.1 м.6 | `$02D696` | старт на тике $1194; повтор каждые $0708; на тике 5400; на тике 5400; музыка 21 = банк 3 песня $88; зовёт PlaySound, StageSpreadTerrainTick |
| 25 | гл.1 м.8 | `$02D6D6` | старт на тике $1518; повтор каждые $0A8C; на тике 7200; на тике 7200; музыка 21 = банк 3 песня $88; зовёт PlaySound, FadePaletteSlow, StageSpreadTerrainTick |
| 26 | гл.1 м.11 | `$02D71C` | старт на тике $4650; повтор каждые $0258; на тике 18000; музыка 59 = банк 3 песня $86; зовёт PlaySound, StageConvertWaveTick |
| 27 | гл.1 м.21 | `$02D786` | старт на тике $3840; повтор каждые $0384; зовёт StageSpreadType8Tick |
| 28 | гл.1 м.12 | `$02D74C` | на тике 7200; на тике 7200; музыка 67 = банк 3 песня $85; зовёт PlaySound, LoadStagePalette10 |
| 29 | гл.1 м.16 | `$02D844` | параметр d7 = 50; зовёт LoseIfNeutralTypeGone |
| 30 | гл.1 м.18 | `$02D8EE` | старт на тике $3840; повтор каждые $0708; параметр d7 = 50; на тике 13500; на тике 13500; музыка 21 = банк 3 песня $88; зовёт LoseIfNeutralTypeGone, PlaySound, FadePaletteSlow, StageSpreadTerrainTick |
| 31 | гл.1 м.34 | `$02DC1E` | старт на тике $1FA4; повтор каждые $0708; на тике 8100; музыка 73 = банк 2 песня $8A; зовёт LoadStagePalette, PlaySound, RepaintLastCellOfType, ShakeScreen |
| 32 | гл.1 м.35 | `$02DD54` | старт на тике $8CA0; зовёт StageSoundLoopTick |
| 33 | гл.1 м.15 | `$02D946` | старт на тике $34BC; повтор каждые $0258; на тике 13500; музыка 59 = банк 3 песня $86; зовёт PlaySound, StageConvertWaveTick, StartScreenShudder, ConvertTerrainInner |
| 34 | гл.1 м.17 | `$02D8E4` | параметр d7 = 50; зовёт LoseIfNeutralTypeGone |
| 35 | гл.1 м.20 | `$02D87E` | старт на тике $2328; повтор каждые $012C; на тике 9000; на тике 9005; музыка 19 = банк 3 песня $87; зовёт PlaySound, StageSpreadRandom89Tick, LoadPlacement |
| 36 | гл.1 м.23 | `$02D93C` | параметр d7 = 50; зовёт LoseIfNeutralTypeGone |
| 37 | гл.1 м.44 | `$02D9CC` | старт на тике $AFC8; повтор каждые $003C; музыка 17 = банк 4 песня $83; музыка 21 = банк 3 песня $88; зовёт TickLavaEruption, Species18StepGate |
| 38 | гл.1 м.40 | `$02D794` | на тике 12600; на тике 12600; музыка 101 = банк 4 песня $8D; зовёт PlaySound, LoadStagePalette |
| 39 | гл.1 м.29 | `$02D806` | старт на тике $1518; повтор каждые $0003; зовёт StagePoisonTick |
| 40 | гл.1 м.28 | `$02DD5E` | старт на тике $8CA0; повтор каждые $0A8C; на тике 36000; на тике 36000; музыка 21 = банк 3 песня $88; зовёт PlaySound, FadePaletteSlow, StageSpreadTerrainTick |
| 41 | гл.1 м.42 | `$02D814` | старт на тике $2328; повтор каждые $00FA; на тике 9000; музыка 67 = банк 3 песня $85; зовёт PlaySound, TickLavaEruption |
| 43 | гл.1 м.30 | `$02D84E` | старт на тике $4650; повтор каждые $01C2; на тике 18000; музыка 61 = банк 2 песня $8E; зовёт PlaySound, StageSpreadWideTick |
| 44 | гл.1 м.24 | `$02DD46` | старт на тике $1C20; повтор каждые $0003; зовёт StagePoisonTick |
| 51 | гл.0 м.1 | `$02DDA6` | параметр d7 = 8; зовёт WinIfHerbivoresReach, ShowMissionNotice |
| 52 | гл.0 м.3 | `$02DE9A` | зовёт ShowMissionNotice |
| 53 | гл.0 м.2 | `$02DF52` | зовёт ShowMissionNotice |
| 54 | гл.0 м.4 | `$02E03E` | зовёт ShowMissionNotice |
| 55 | гл.0 м.5 | `$02E090` | зовёт ShowMissionNotice, RaiseNotice10 |
| 56 | гл.0 м.8 | `$02E12A` | зовёт ShowMissionNotice |
| 57 | гл.0 м.6 | `$02E17C` | зовёт ShowMissionNotice, RaiseNotice14 |
| 58 | гл.0 м.7 | `$02E24A` | зовёт ShowMissionNotice |
| 66 | гл.3 м.4 | `$02E68E` | старт на тике $0708; повтор каждые $0078; зовёт StageSeedType25Tick |
| 67 | гл.3 м.3 | `$02E68E` | старт на тике $0708; повтор каждые $0078; зовёт StageSeedType25Tick |
| 70 | гл.3 м.6 | `$02E2D2` | старт на тике $4650; повтор каждые $0258; на тике 18000; музыка 59 = банк 3 песня $86; зовёт PlaySound, StageConvertWaveTick |
| 71 | гл.3 м.10 | `$02E302` | старт на тике $3840; повтор каждые $0708; на тике 12600; музыка 19 = банк 3 песня $87; зовёт PlaySound, StageSpreadRandomTypeTick |
| 72 | гл.3 м.9 | `$02E342` | старт на тике $3840; повтор каждые $0E10; зовёт StageSpreadWideTick |
| 73 | гл.3 м.7 | `$02E872` | старт на тике $4650; повтор каждые $0E10; зовёт StageSpreadWideTick |
| 76 | гл.3 м.8 | `$02E880` | старт на тике $3138; повтор каждые $0A8C; на тике 14400; на тике 14400; музыка 21 = банк 3 песня $88; зовёт PlaySound, FadePaletteSlow, StageSpreadTerrainTick |
| 77 | гл.8 м.13 | `$02E350` | старт на тике $1518; повтор каждые $2328; зовёт StageConvertInner14Tick |
| 78 | гл.4 м.6 | `$02E35E` | старт на тике $4650; повтор каждые $1518; зовёт StageConvertAll14Tick |
| 80 | гл.3 м.1 | `$02E334` | старт на тике $8CA0; повтор каждые $0708; зовёт StageSpreadWideTick |
| 81 | гл.3 м.2 | `$02E36C` | старт на тике $1518; повтор каждые $2328; на тике 14400; музыка 21 = банк 3 песня $88; зовёт PlaySound, StageConvertInner14Tick |
| 82 | гл.4 м.2 | `$02E39C` | старт на тике $3138; повтор каждые $0708; зовёт StageConvertAll14Tick |
| 83 | гл.8 м.15 | `$02E3AA` | старт на тике $8CA0; повтор каждые $0708; зовёт StageSpreadWideTick |
| 84 | гл.4 м.5 | `$02E3B8` | старт на тике $4650; повтор каждые $1518; зовёт StageSpreadWideTick |
| 85 | гл.4 м.4 | `$02E3C6` | старт на тике $2A30; повтор каждые $0E10; зовёт StageSpreadType8Tick |
| 86 | гл.4 м.8 | `$02E69C` | старт на тике $2328; повтор каждые $D2F0; зовёт StageConvertAll14Once |
| 89 | гл.4 м.9 | `$02E842` | старт на тике $3840; повтор каждые $0003; на тике 14400; музыка 73 = банк 2 песня $8A; зовёт PlaySound, StagePoisonTick |
| 112 | гл.4 м.10, гл.8 м.22 | `$02E3D4` | старт на тике $2328; повтор каждые $0708; на тике 9000; музыка 19 = банк 3 песня $87; зовёт PlaySound, StageSpreadRandomTypeTick |
| 113 | гл.5 м.4 | `$02E404` | старт на тике $1518; повтор каждые $0708; на тике 5400; музыка 19 = банк 3 песня $87; зовёт PlaySound, StageSpreadRandomTypeTick |
| 114 | гл.5 м.2 | `$02E434` | старт на тике $0708; повтор каждые $0078; зовёт StageSeedType25Tick |
| 116 | — | `$02E442` | старт на тике $2A30; повтор каждые $0708; на тике 9000; на тике 9000; музыка 21 = банк 3 песня $88; зовёт PlaySound, FadePaletteSlow, StageSpreadTerrainTick |
| 117 | гл.8 м.21 | `$02E488` | повтор каждые $0708; на тике 5400; зовёт StageSpreadRandomTypeTick, StartScreenShudder, ConvertTerrainInner, FlushScreenCellMarks |
| 119 | гл.5 м.5 | `$02E570` | старт на тике $1C20; на тике 7200; музыка 101 = банк 4 песня $8D; зовёт PlaySound, StageSoundLoopTick |
| 120 | гл.5 м.6 | `$02E59C` | старт на тике $2A30; повтор каждые $0708; на тике 10800; музыка 67 = банк 3 песня $85; зовёт PlaySound, StageShudderTick |
| 121 | — | `$02E5CC` | старт на тике $2A30; повтор каждые $00FA; на тике 10800; музыка 67 = банк 3 песня $85; зовёт PlaySound, TickLavaEruption |
| 122 | — | `$02E5FC` | старт на тике $1C20; повтор каждые $1518; на тике 7200; музыка 61 = банк 2 песня $8E; зовёт PlaySound, StageSpreadWideTick |
| 125 | гл.8 м.23 | `$02E62C` | старт на тике $0708; повтор каждые $00FA; зовёт TickLavaEruption |
| 127 | гл.5 м.8 | `$02E63A` | старт на тике $2A30; повтор каждые $0708; зовёт StageSpreadType8Tick |
| 129 | — | `$02E648` | старт на тике $34BC; повтор каждые $0708; на тике 5400; на тике 12600; музыка 21 = банк 3 песня $88; зовёт PlaySound, FadePaletteSlow, StageSpreadTerrainTick |
| 130 | гл.5 м.7 | `$02E6AA` | старт на тике $3840; на тике 14400; музыка 101 = банк 4 песня $8D; зовёт PlaySound, StageSoundLoopTick |
| 131 | гл.5 м.3 | `$02E6E4` | на тике 7200; на тике 7200; музыка 67 = банк 3 песня $85; зовёт PlaySound, LoadStagePalette |
| 132 | — | `$02E722` | на тике 4500; музыка 19 = банк 3 песня $87; зовёт PlaySound, ShakeScreen, SpreadTerrainRandom, ConvertTerrainAll |
| 217 | гл.8 м.12 | `$02E6D6` | старт на тике $5B68; повтор каждые $0E10; зовёт StageSpreadType8Tick |
| 222 | гл.8 м.20 | `$02E836` | параметр d7 = 68; зовёт AllowWinIfNeutralTypeGone |
| 223 | гл.8 м.24 | `$02E8C6` | зовёт FindUnitFromRandomStart, loc_01F410, ScrollToClampedCell |

## Что делается при входе на карту

Таблица `table_stagestart` `$02CE90` устроена так же, но тела у неё
короткие: почти все сводятся к одному вызову. Смысл вызова виден из
`$0166B2`, который каждый кадр решает, кончилась ли миссия: после
первых `$200` тиков он смотрит перепись обоих игроков, и если у
второго не осталось юнитов, ставит победу — **но перед этим
умножает её на байт `WipeoutWinAllowed`**. Поэтому обработчик входа
фактически задаёт цель миссии: `EnableWipeoutWin` — «перебей всех и
победил», `DisableWipeoutWin` — «этого мало».

Из 256 этапов 229 обходятся ровно этим вызовом и ничем больше.
Различных адресов 19, но различных тел всего 7: одинаковые
восьмибайтовые кусочки размножены, а не разделены.

| этап | миссии | вход | тело |
|---|---|---|---|
| 3 | гл.1 м.7 | `$02E91A` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 7 | гл.1 м.13 | `$02E906` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 11 | гл.1 м.19 | `$02E91A` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 17 | гл.1 м.36 | `$02E92E` | bsr.w SetSpreadingTerrainWide / jsr (EnableWipeoutWin).l / rts |
| 20 | гл.1 м.45 | `$02E942` | jsr (DisableWipeoutWin).l / bsr.w StartFinalCollapse / rts |
| 23 | гл.1 м.4 | `$02E95E` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 26 | гл.1 м.11 | `$02E95E` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 27 | гл.1 м.21 | `$02E906` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 31 | гл.1 м.34 | `$02E92E` | bsr.w SetSpreadingTerrainWide / jsr (EnableWipeoutWin).l / rts |
| 35 | гл.1 м.20 | `$02E95E` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 43 | гл.1 м.30 | `$02E95E` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 51 | гл.0 м.1 | `$02E972` | jsr (DisableWipeoutWin).l / rts |
| 72 | гл.3 м.9 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 73 | гл.3 м.7 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 77 | гл.8 м.13 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 78 | гл.4 м.6 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 80 | гл.3 м.1 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 81 | гл.3 м.2 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 82 | гл.4 м.2 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 83 | гл.8 м.15 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 84 | гл.4 м.5 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 85 | гл.4 м.4 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 86 | гл.4 м.8 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 122 | — | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 127 | гл.5 м.8 | `$02E982` | bsr.w SetSpreadingTerrain / jsr (EnableWipeoutWin).l / rts |
| 222 | гл.8 м.20 | `$02E9B8` | lea data_245(pc),a6 / jsr (LoadPlacement).l / jsr (DisableWipeoutWin).l / rts |
| 255 | гл.8 м.5, гл.8 м.9 | `$02E99E` | jsr (Random).l / andi.l #$00000007,d0 / move.l d0,(GameTick).l / jsr (EnableWipeoutWin).l / rts |

## Общие тела: что именно происходит

Сценарий сам почти ничего не делает — он задаёт `d6` и `d7` и зовёт
тело из библиотеки около `$02F1D2`. У всех тел один скелет:

```
    d0 = StageEventTimer
    если d0 == 0:  сработать, когда GameTick дорастёт до d7
    иначе:         d0 -= 1; сработать на нуле
    сработав:      <действие>; StageEventTimer = d6
```

Действие почти всегда — **проход по карте местности**. Соглашение у
всех четырёх проходов одно: `d4` — маска типов, которые можно
менять (бит по номеру типа), `d5` — тип, в который менять.

| проход | охват |
|---|---|
| `ConvertTerrainAll` | 40x40, все клетки |
| `ConvertTerrainInner` | 38x38, все клетки |
| `SeedEmptyTerrain` | только пустые, шанс 25% |
| `SpreadTerrainRandom` | 38x38, шанс 10% |

Несколько тел местность не трогают, а **проверяют цель миссии**.
У них `d7` значит не тик, а тип или число, и кладут его байтом:

| тело | смысл | где |
|---|---|---|
| `LoseIfNeutralTypeGone` | не осталось нейтрального юнита типа `d7` — поражение | этапы 29, 30, 34, 36, всюду тип 50 |
| `AllowWinIfNeutralTypeGone` | не осталось типа `d7` — победу разрешить | этап 222, тип 68 |
| `WinIfHerbivoresReach` | травоядных у игрока 1 стало `>= d7` — победа | этап 51, восемь |

Последние два стоят на картах, где обработчик входа победу
запретил, — так и получаются цели, отличные от «перебей всех».

Тела, которые зовут сценарии:

| тело | этапы | действие |
|---|---|---|
| `StageSpreadWideTick` | 23, 43, 72, 73, 80, 83, 84, 122 | местность не трогает; зовёт RunEventAnimation60, loc_020EE4, SpreadTypeMapWide |
| `ShowMissionNotice` | 51, 52, 53, 54, 55, 56, 57, 58 | местность не трогает; зовёт CheckNoticeConditions |
| `StageSpreadTerrainTick` | 24, 25, 30, 40, 76, 116, 129 | типы 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 15, 17, 18, 21 -> 16 (`SpreadTerrainRandom`) |
| `StageSpreadRandomTypeTick` | 4, 71, 112, 113, 117 | типы 16 -> 8 либо 9 либо 5 (`SpreadTerrainRandom`); типы 14 -> 19 (`ConvertTerrainInner`) |
| `TickLavaEruption` | 9, 37, 41, 121, 125 | местность не трогает; зовёт LavaFlowWide, RebuildGrowthFlagMap, EruptionFlashAndShake, LavaFlowDown |
| `StageSoundLoopTick` | 13, 19, 32, 119, 130 | местность не трогает; зовёт RefreshScreenKeepFlags |
| `StagePoisonTick` | 14, 39, 44, 89 | местность не трогает; зовёт ForEachUnitBothPlayers, ShowPoisonEventIcon |
| `StageSeedType25Tick` | 5, 66, 67, 114 | пусто -> 25 (`SeedEmptyTerrain`) |
| `StageConvertWaveTick` | 16, 26, 33, 70 | типы 0 -> 8 (`SpreadTerrainRandom`); типы 1, 2, 3, 4, 5, 6, 7 -> 9 (`SpreadTerrainRandom`); типы 17, 18 -> 0 (`SpreadTerrainRandom`) |
| `StageSpreadType8Tick` | 27, 85, 127, 217 | типы 19 -> 8 (`SpreadTerrainRandom`) |
| `LoseIfNeutralTypeGone` | 29, 30, 34, 36 | местность не трогает; зовёт ForceMissionLoss |
| `StageConvertInner14Tick` | 11, 77, 81 | типы 19 -> 14 (`ConvertTerrainInner`) |
| `ScrollToClampedCell` | 12, 17, 223 | местность не трогает; зовёт ClampMapCoords, ScrollCursorToTarget, DrawMarkAtCell, PaintCellFire |
| `StageConvertAll14Once` | 3, 86 | типы 19 -> 14 (`ConvertTerrainAll`) |
| `StageShudderTick` | 7, 120 | типы 19 -> 8 (`ConvertTerrainInner`) |
| `Species18StepGate` | 37 | местность не трогает; зовёт  |
| `StageConvertAll14Tick` | 78, 82 | типы 19 -> 14 (`ConvertTerrainAll`) |
| `StageSpreadType25Tick` | 2 | типы 24 -> 25 (`SpreadTerrainRandom`) |
| `StageShakeAtTick708` | 17 | местность не трогает; зовёт ShakeScreen, SetStageAnimByte0, FadePaletteRow3, SetSceneMode1, SetSceneByte5 |
| `StageBurnRandomUnitCell` | 17 | местность не трогает; зовёт FindUnitFromRandomStart, PaintCellFire |
| `StageSpecies18MarchTick` | 20 | местность не трогает; зовёт TickSpecies18March |
| `StageSpreadRandom89Tick` | 35 | типы 16 -> 8 либо 9 либо 5 (`SpreadTerrainRandom`); типы 14 -> 19 (`ConvertTerrainAll`) |
| `WinIfHerbivoresReach` | 51 | местность не трогает; зовёт ForceMissionWin |
| `RaiseNotice10` | 55 | местность не трогает; зовёт SessionSetBit32 |
| `RaiseNotice14` | 57 | местность не трогает; зовёт SessionSetBit32 |
| `PlaceTerrainListFiltered` | 132 | местность не трогает; зовёт PaintCellAtIndex |
| `AllowWinIfNeutralTypeGone` | 222 | местность не трогает; зовёт EnableWipeoutWin |
