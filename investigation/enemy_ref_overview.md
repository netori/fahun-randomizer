# 与参考实现敌人名单的对照

来源：`enemy.txt`（23174 条，覆盖 394 个模型，人工维护）

两边都有的模型 **388**，其中 Boss 判定一致 **359（92.5%）**

不一致 29 个（前 40）：

| 模型 | 参考 | 我们 | Tags |
|---|---|---|---|
| c3181 | Basic×4/Boss×1/MinorBoss×1 | normal×6/boss×2 | exclude:unkillable;exclude:unkillable perceptive;exclude:unkillable perceptive b |
| c3250 | Basic×1/Miniboss×1 | boss×1/normal×1 | exclude:unkillable;exclude:unkillable partial size:2;Draconic Tree Sentinel Boss |
| c3251 | Miniboss×3 | boss×3 | exclude:unkillable;exclude:unkillable sensitive;Tree Sentinel;Tree Sentinel Helm |
| c3451 | Basic×21/None×4/MinorBoss×1 | normal×11/boss×1 | exclude:unkillable partial;Scaly Misbegotten Boss;32002802;1039505100;32005100 |
| c3550 | Basic×7/MinorBoss×1 | normal×4/boss×1 | 1040535102;12055102;exclude:unkillable;exclude:unkillable partial size:1 arena:1 |
| c3600 | Basic×6/MinorBoss×1/Evergaol×1 | normal×6/boss×2 | exclude:unkillable;exclude:unkillable adjective arena:1;exclude:unkillable npcit |
| c3701 | Basic×20/Helper×1/None×1 | boss×9 | 1036515100;11005106;30125100;multi mainhelper swappable proper;Perfumer Tricia |
| c4020 | Basic×15/MinorBoss×1 | normal×11/boss×1 | exclude:unkillable npcitem;exclude:unkillable partial arena:1 size:1;generated e |
| c4130 | MinorBoss×2/Miniboss×1/Basic×1 | elite×3/boss×1 | exclude:unkillable;exclude:unkillable proper;exclude:unkillable proper arena:1;e |
| c4311 | Basic×78/MinorBoss×1 | normal×19 | exclude:unkillable perceptive proper arena:0;perceptive;sensitive;Soldier of God |
| c4500 | Helper×1/DragonMiniboss×2 | boss×3 | exclude:unkillable perceptive proper size:2;multi perceptive noplace;Flying Drag |
| c4501 | DragonMiniboss×1 | boss×1 | exclude:unkillable perceptive proper adjective size:3;Decaying Ekzykes;104837510 |
| c4630 | Basic×27/MinorBoss×1 | normal×13 | allowframes;exclude:unkillable;exclude:unkillable arena:1 size:1;exclude:unkilla |
| c4660 | Basic×17/MinorBoss×1 | normal×18/boss×2 | allowframes perceptive;exclude:unkillable perceptive;exclude:unkillable resist p |
| c4680 | MinorBoss×1/Miniboss×2 | elite×2/boss×1 | exclude:unkillable perceptive adjective exclude:fallout size:2 arena:2;exclude:u |
| c4690 | Basic×5/MinorBoss×1 | normal×4/boss×2 | exclude:unkillable allowframes perceptive;exclude:unkillable perceptive;exclude: |
| c4810 | Basic×2/Miniboss×4/Helper×3 | boss×1 | exclude:unkillable;exclude:unkillable partial size:2;multi exclude:unkillable pa |
| c4811 | Basic×2/Miniboss×3 | boss×1/elite×1 | exclude:unkillable;exclude:unkillable resist noswamp partial size:2;Putrid Avata |
| c4820 | Basic×4/Helper×1/None×4/Miniboss×1 | boss×11 | exclude:unkillable adjective exclude:fallout size:1 arena:2;exclude:unkillable n |
| c4911 | Miniboss×1 | boss×1 | exclude:unkillable perceptive nomodelname proper adjective size:2;Great Wyrm The |
| c4950 | Miniboss×3/Basic×1 | boss×2/elite×2 | exclude:unkillable;exclude:unkillable resist mariner noswamp partial size:1;excl |
| c4980 | NightMiniboss×7/None×1/Miniboss×1 | boss×6/elite×3 | exclude:unkillable resist perceptive nomodelname noswamp partial;exclude:unkilla |
| c5040 | Basic×11/MinorBoss×1 | normal×9/boss×1 | exclude:unkillable perceptive proper;perceptive;Curseblade Labirith;Curseblade M |
| c5081 | MinorBoss×1/Basic×2 | normal×3/boss×2 | exclude:unkillable manualname partial arena:1;exclude:unkillable npcitem;Chief B |
| c5370 | DragonMiniboss×1 | boss×1 | exclude:unkillable perceptive proper size:2;Ancient Dragon Senessax;2054395100 |
| c5810 | MinorBoss×1/Basic×1 | elite×2/boss×1 | exclude:unkillable npcitem perceptive;exclude:unkillable perceptive proper;Demi- |
| c5840 | Basic×26/None×1/Miniboss×2 | boss×18 | exclude:unkillable;exclude:unkillable bossgroup proper arena:1;multi;multi fight |
| c5860 | DragonMiniboss×3 | boss×3 | exclude:unkillable resist perceptive noswamp fight wyvern manualname adjective s |
| c7100 | MinorBoss×2/Evergaol×1/Basic×8 | normal×2/boss×2 | exclude:unkillable perceptive size:1;exclude:unkillable size:1;Ancient Hero of Z |

只有参考实现有：6 个；只有我们有：68 个
