# 体型档：参考实现 vs 我们

参考实现有 size 档的模型 79 个（我们这边可比 79 个）

交叉表（行=参考 size:N，列=我们的桶 0/1/2）：

| ref\我们 | 0 | 1 | 2 | 合计 |
|---|---|---|---|---|
| 1 | 3 | 4 | 9 | 16 |
| 2 | 0 | 7 | 9 | 16 |
| 3 | 0 | 0 | 0 | 0 |

逐模型：

| 模型 | 参考 size | 我们桶 | 半径 | 高 | 行数 | 参考名 |
|---|---|---|---|---|---|---|
| c3400 | 1 | 1 | 0.5 | 2.2 | 15 | Frenzied Duelist、Grave Warden Duelist Bo |
| c4340 | 1 | 2 | 1.0 | 3.5 | 14 | Mad Pumpkin Head (Flail)、Mad Pumpkin Hea |
| c4480 | 1 | 1 | 0.65 | 1.9 | 13 | Miranda Blossom and Sprouts、Miranda Omen |
| c4630 | 1 | 3 | 2.3 | 5.0 | 13 | Runebear Boss |
| c4020 | 1 | 2 | 1.5 | 1.5 | 12 | Royal Revenant Boss |
| c4820 | 1 | 2 | 0.6 | 2.8 | 11 | Omenkiller、Omenkiller Boss |
| c3810 | 1 | 2 | 0.8 | 2.4 | 10 | Kindred of Rot、Kindred of Rot Duo |
| c2100 | 1 | 0 | 0.4 | 1.9 | 9 | Alecto, Black Knife Ringleader、Black Kni |
| c4260 | 1 | 2 | 1.2 | 2.4 | 9 | Erdtree Burial Watchdog (Scepter)、Erdtre |
| c3460 | 1 | 2 | 0.8 | 2.4 | 6 | Leonine Misbegotten Boss、Misbegotten Cru |
| c4690 | 1 | 3 | 2.0 | 3.0 | 6 | Grafted Scion Boss |
| c3550 | 1 | 1 | 0.7 | 2.2 | 5 | Sanguine Noble Boss |
| c3664 | 1 | 0 | 0.3 | 1.8 | 5 | Cemetery Shade Boss、Cemetery Shade and S |
| c4950 | 1 | 3 | 1.5 | 4.0 | 4 | Tibia Mariner Boss |
| c7100 | 1 | 2 | 0.5 | 2.6 | 4 | Ancient Hero of Zamor Boss |
| c2110 | 1 | 3 | 2.5 | 3.6 | 3 | Beast Clergyman、Maliketh, the Black Blad |
| c5020 | 1 | 3 | 1.1 | 3.9 | 2 | Putrescent Knight |
| c5130 | 1 | 0 | 0.5 | 0.5 | 2 | Base Serpent Messmer、Messmer the Impaler |
| c5300 | 1 | 2 | 0.4 | 2.4 | 2 | Rellana, Twin Moon Knight |
| c5820 | 1 | 3 | 2.3 | 5.0 | 2 | Ralva the Great Red Bear、Rugalea the Gre |
| c2190 | 1 | 2 | 0.5 | 2.6 | 1 | Radagon of the Golden Order |
| c5010 | 1 | 3 | 3.7 | 7.5 | 1 | Golden Hippopotamus |
| c5312 | 1 | 1 | 0.5 | 2.3 | 1 | Jori, Elder Inquisitor |
| c0000 | 2 | 1 | 0.1 | 0.3 | 323 | Adan, Thief of Fire、Ancient Dragon-Man、C |
| c3300 | 2 | 1 | 0.4 | 2.3 | 28 | Ant-Riding Nox Swordstress、Nox Duo、Nox S |
| c2140 | 2 | 2 | 0.8 | 3.1 | 23 | Fell Twin、Fell Twin Duo |
| c4140 | 2 | 1 | 0.6 | 1.0 | 22 | Crucible Spiritcaller Snail、Godskin Spir |
| c4660 | 2 | 3 | 2.0 | 12.5 | 20 | Guardian Golem Boss |
| c3350 | 2 | 2 | 0.4 | 2.8 | 19 | Crystalian (Spear)、Crystalian Ringblade  |
| c3970 | 2 | 1 | 0.65 | 2.0 | 18 | Beastman of Farum Azula (Throwing Knife) |
| c3800 | 2 | 2 | 0.5 | 2.4 | 17 | Cleanrot Knight (Sickle)、Cleanrot Knight |
| c2500 | 2 | 1 | 0.5 | 2.3 | 16 | Crucible Knight、Crucible Knight Boss、Cru |
| c4470 | 2 | 3 | 1.1 | 4.3 | 13 | Abductor Virgin (Wheel)、Abductor Virgin  |
| c4980 | 2 | 3 | 3.0 | 8.0 | 9 | Death Rite Bird、Deathbird |
| c3181 | 2 | 2 | 1.0 | 3.0 | 8 | Red Wolf of Radagon、Red Wolf of the Cham |
| c4120 | 2 | 1 | 0.7 | 2.2 | 8 | Demi-Human Chief、Demi-Human Chief Duo |
| c4640 | 2 | 3 | 3.7 | 7.5 | 8 | Putrid Tree Spirit Boss、Ulcerated Tree S |
| c4620 | 2 | 3 | 8.0 | 12.0 | 7 | Astel, Naturalborn of the Void、Astel, St |
| c4650 | 2 | 3 | 4.0 | 8.5 | 6 | Dragonkin Soldier Boss、Dragonkin Soldier |
| c5230 | 2 | 3 | 4.95 | 8.0 | 6 | Scadutree Avatar |
| c2130 | 2 | 3 | 0.9 | 3.6 | 4 | Capital Outskirts Margit、Margit, the Fel |
| c3560 | 2 | 2 | 0.7 | 2.9 | 4 | Godskin Apostle、Godskin Duo |
| c3570 | 2 | 2 | 1.3 | 3.0 | 4 | Godskin Noble、Godskin Noble Boss |
| c4502 | 2 | 3 | 7.0 | 14.0 | 4 | Glintstone Dragon Adula、Glintstone Drago |
| c4510 | 2 | 3 | 7.0 | 14.1 | 4 | Ancient Dragon Lansseax |
| c4670 | 2 | 3 | 5.0 | 6.0 | 4 | Ancestor Spirit、Regal Ancestor Spirit |
| c4910 | 2 | 3 | 3.0 | 8.0 | 4 | Magma Wyrm Boss、Magma Wyrm Makar |
| c4500 | 2 | 3 | 10.0 | 10.0 | 3 | Flying Dragon Agheel、Flying Dragon Greyl |
| c4580 | 2 | 3 | 1.7 | 11.0 | 3 | Wormface Boss |
| c4680 | 2 | 3 | 2.0 | 6.0 | 3 | Full-Grown Fallingstar Beast、Regular Fal |
| c5580 | 2 | 3 | 7.0 | 14.0 | 3 | Jagged Peak Drake Boss |
| c5860 | 2 | 3 | 7.0 | 14.0 | 3 | Ghostflame Dragon Boss、Ghostflame Dragon |
| c2030 | 2 | 3 | 0.6 | 4.0 | 2 | Rennala 1 |
| c2120 | 2 | 2 | 0.4 | 2.4 | 2 | Malenia, Blade of Miquella |
| c3050 | 2 | 2 | 0.8 | 3.0 | 2 | Commander Niall、Commander O'Neil |
| c3250 | 2 | 3 | 1.1 | 3.9 | 2 | Draconic Tree Sentinel Boss |
| c4800 | 2 | 3 | 1.3 | 4.0 | 2 | Mohg, Lord of Blood、Mohg, the Omen |
| c4811 | 2 | 3 | 1.8 | 4.6 | 2 | Putrid Avatar Boss |
| c5210 | 2 | 3 | 3.5 | 2.4 | 2 | Divine Beast Dancing Lion、Divine Beast D |
| c2031 | 2 | 3 | 0.8 | 4.0 | 1 | Rennala 2 |
| c4511 | 2 | 3 | 7.0 | 14.1 | 1 | Lichdragon Fortissax |
| c4721 | 2 | 3 | 0.9 | 3.7 | 1 | Hoarah Loux, Warrior |
| c4750 | 2 | 2 | 1.3 | 2.0 | 1 | Godefroy the Grafted、Godrick the Grafted |
| c4810 | 2 | 3 | 1.8 | 4.6 | 1 | Erdtree Avatar、Erdtree Avatar Boss、Erdtr |
| c4911 | 2 | 3 | 3.0 | 8.0 | 1 | Great Wyrm Theodorix |
| c5000 | 2 | 3 | 1.1 | 3.9 | 1 | Commander Gaius |
| c5030 | 2 | 3 | 1.5 | 3.9 | 1 | Romina, Saint of the Bud |
| c5051 | 2 | 1 | 0.5 | 2.3 | 1 | Midra, Lord of Frenzied Flame |
| c5120 | 2 | 3 | 10.0 | 10.0 | 1 | Bayle the Dread |
| c5370 | 2 | 3 | 7.0 | 14.1 | 1 | Ancient Dragon Senessax |
| c6260 | 2 | 3 | 3.0 | 8.0 | 1 | Death Rite Bird |
| c6310 | 2 | 3 | 4.0 | 6.0 | 1 | Regular Fallingstar Beast |
| c4770 | 3 | 3 | 1.5 | 8.0 | 8 | Black Blade Kindred、Valiant Gargoyle (Tw |
| c5220 | 3 | 3 | 1.0 | 4.0 | 3 | Promised Consort Radahn、Radahn, Consort  |
| c4710 | 3 | 3 | 7.5 | 13.0 | 2 | God-Devouring Serpent、Rykard, Lord of Bl |
| c2200 | 3 | 3 | 7.0 | 10.0 | 1 | Elden Beast |
| c4501 | 3 | 3 | 12.0 | 12.0 | 1 | Decaying Ekzykes |
| c4520 | 3 | 3 | 10.0 | 10.0 | 1 | Dragonlord Placidusax |
| c5200 | 3 | 3 | 5.0 | 5.0 | 1 | Metyr, Mother of Fingers |
