# 与参考实现敌人名单的对照

来源：`enemy.txt`（23174 条，覆盖 394 个模型，人工维护）

两边都有的模型 **388**，其中 Boss 判定一致 **339（87.4%）**

不一致 49 个（前 40）：

| 模型 | 参考 | 我们 | Tags |
|---|---|---|---|
| c0000 | None×273/HostileNPC×54/Boss×3/Helper×22/Basic×6/MinorBoss×11/Evergaol×2 | skip×275/elite×2/boss×23/normal×23 | alwayschr noplace;exclude:unkillable;exclude:unkillable encounter invader;exclud |
| c2130 | Boss×2/Basic×1 | elite×2/boss×2 | exclude:unkillable manualname minibosslite;exclude:unkillable perceptive exclude |
| c2140 | Basic×32/MinorBoss×1/Helper×1 | elite×11/skip×9/boss×3 | 10005104;1044535100;34145100;exclude:unkillable;exclude:unkillable npcitem;multi |
| c2500 | Basic×9/Miniboss×1/None×1/Helper×11/MinorBoss×2/Evergaol×1 | normal×12/boss×2/skip×2 | exclude:unkillable;exclude:unkillable bossgroup exclude:fallout;exclude:unkillab |
| c3181 | Basic×4/Boss×1/MinorBoss×1 | elite×6/boss×2 | exclude:unkillable;exclude:unkillable perceptive;exclude:unkillable perceptive b |
| c3250 | Basic×1/Miniboss×1 | boss×1/elite×1 | exclude:unkillable;exclude:unkillable partial size:2;Draconic Tree Sentinel Boss |
| c3251 | Miniboss×3 | boss×3 | exclude:unkillable;exclude:unkillable sensitive;Tree Sentinel;Tree Sentinel Helm |
| c3300 | Basic×18/None×1/MinorBoss×1/Helper×1 | normal×24/skip×1/boss×3 | multi exclude:unkillable perceptive manualname partial arena:1 size:2;multi manu |
| c3350 | Basic×16/MinorBoss×4/Helper×4 | normal×11/boss×8 | exclude:unkillable bossgroup manualname adjective;generated;multi exclude:unkill |
| c3400 | Basic×4/MinorBoss×4/None×1 | elite×12/boss×3 | exclude:unkillable;exclude:unkillable bossgroup perceptive adjective arena:1;exc |
| c3451 | Basic×21/None×4/MinorBoss×1 | skip×5/normal×6/boss×1 | exclude:unkillable partial;Scaly Misbegotten Boss;32002802;1039505100;32005100 |
| c3460 | Basic×4/MinorBoss×2/Boss×1/Helper×1 | normal×3/boss×3 | 1043305100;1051365100;11005106;30125100;31125100;exclude:unkillable partial size |
| c3550 | Basic×7/MinorBoss×1 | normal×4/boss×1 | 1040535102;12055102;exclude:unkillable;exclude:unkillable partial size:1 arena:1 |
| c3570 | Helper×2/Boss×1/Basic×1 | elite×2/boss×2 | exclude:unkillable manualname minibosslite partial;exclude:unkillable perceptive |
| c3600 | Basic×6/MinorBoss×1/Evergaol×1 | normal×6/boss×2 | exclude:unkillable;exclude:unkillable adjective arena:1;exclude:unkillable npcit |
| c3800 | Basic×36/MinorBoss×2/Helper×1/None×2 | normal×10/skip×5/boss×2 | exclude:unkillable resist arena:1;generated;multi exclude:unkillable resist manu |
| c3810 | Basic×53/MinorBoss×1/Helper×1/None×1 | normal×5/skip×4/boss×1 | 12015110;31075100;multi exclude:unkillable manualname arena:1 size:1;multi mainh |
| c3970 | Basic×55/MinorBoss×2/Helper×1 | normal×17/boss×1 | exclude:unkillable perceptive friendly;multi exclude:unkillable manualname size: |
| c4020 | Basic×15/MinorBoss×1 | normal×11/boss×1 | exclude:unkillable npcitem;exclude:unkillable partial arena:1 size:1;generated e |
| c4120 | Basic×10/MinorBoss×1/Helper×1 | normal×5/skip×1/boss×2 | exclude:unkillable;multi exclude:unkillable manualname size:2;multi mainhelper s |
| c4130 | MinorBoss×2/Miniboss×1/Basic×1 | elite×3/boss×1 | exclude:unkillable;exclude:unkillable proper;exclude:unkillable proper arena:1;e |
| c4140 | Basic×144/DupeOnly×9/MinorBoss×2/Helper×3 | normal×19/boss×3 | exclude:unkillable;multi exclude:unkillable perceptive manualname partial size:2 |
| c4260 | MinorBoss×5/Helper×1/Basic×8 | elite×5/boss×4 | exclude:unkillable;exclude:unkillable bossgroup resist perceptive noswamp manual |
| c4290 | Helper×1/Basic×4/MinorBoss×1/Evergaol×1 | normal×5/boss×2 | exclude:unkillable arena:1;exclude:unkillable npcitem;exclude:unkillable percept |
| c4311 | Basic×78/MinorBoss×1 | normal×19 | exclude:unkillable perceptive proper arena:0;perceptive;sensitive;Soldier of God |
| c4340 | Basic×11/MinorBoss×2/Helper×1 | normal×11/boss×2/skip×1 | 1033475100;1044365102;1048405100;exclude:unkillable partial arena:0;multi exclud |
| c4470 | Basic×19/Helper×1/MinorBoss×1/None×1 | elite×8/skip×2/boss×2/normal×1 | 14005104;16005860;34125102;multi exclude:unkillable resist perceptive noswamp ma |
| c4480 | Basic×55/MinorBoss×2 | elite×11/boss×2 | 1034445100;1036515100;1041515104;12015104;31025100;31185100;exclude:unkillable;m |
| c4500 | Helper×1/DragonMiniboss×2 | boss×1/skip×1/elite×1 | exclude:unkillable perceptive proper size:2;multi perceptive noplace;Flying Drag |
| c4501 | DragonMiniboss×1 | boss×1 | exclude:unkillable perceptive proper adjective size:3;Decaying Ekzykes;104837510 |
| c4620 | Basic×2/Boss×1/None×1/MinorBoss×1/Helper×8 | boss×3/skip×4 | exclude:unkillable perceptive manualname;multi exclude:unkillable perceptive pro |
| c4630 | Basic×27/MinorBoss×1 | skip×13 | allowframes;exclude:unkillable;exclude:unkillable arena:1 size:1;exclude:unkilla |
| c4660 | Basic×17/MinorBoss×1 | elite×14/skip×4/boss×2 | allowframes perceptive;exclude:unkillable perceptive;exclude:unkillable resist p |
| c4670 | Boss×2 | elite×2/boss×2 | exclude:unkillable perceptive nomodelname size:2 arena:3;multi exclude:unkillabl |
| c4680 | MinorBoss×1/Miniboss×2 | elite×2/boss×1 | exclude:unkillable perceptive adjective exclude:fallout size:2 arena:2;exclude:u |
| c4690 | Basic×5/MinorBoss×1 | elite×4/boss×2 | exclude:unkillable allowframes perceptive;exclude:unkillable perceptive;exclude: |
| c4720 | Boss×2 | skip×1 | exclude:unkillable perceptive scalephase manualname exclude:fallout exclude:stra |
| c4770 | Basic×13/Boss×1/Helper×1/None×2/Miniboss×2 | elite×5/boss×2/normal×1 | exclude:unkillable;exclude:unkillable resist noswamp partial size:2;exclude:unki |
| c4810 | Basic×2/Miniboss×4/Helper×3 | boss×1 | exclude:unkillable;exclude:unkillable partial size:2;multi exclude:unkillable pa |
| c4811 | Basic×2/Miniboss×3 | boss×1/elite×1 | exclude:unkillable;exclude:unkillable resist noswamp partial size:2;Putrid Avata |

只有参考实现有：6 个；只有我们有：68 个
