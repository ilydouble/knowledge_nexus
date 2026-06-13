# SHIFDR 数据分析报告

> 本报告旨在为后续知识图谱提取提供结构化的领域理解。报告从数据集概述、实体识别、关系建模、属性分类、层级结构等多个维度进行洞察，为图谱的节点/边设计提供依据。

---

## 1. 数据集概述

**SHIFDR**（Sub-metered HVAC Implemented For Demand Response）是密歇根大学发布的商业建筑 HVAC 需求响应实验数据集，涵盖美国密歇根州东南部 14 栋商业建筑 2017–2021 年夏季的测量数据。

- **数据来源**: [Deep Blue](https://deepblue.lib.umich.edu/data/collections/vh53ww273?locale=en)
- **DOI**: doi:10.7302/vmwh-ek70
- **许可**: Creative Commons BY-NC 4.0
- **资助方**: 美国能源部(DOE)、美国国家科学基金会(NSF)
- **当前子集**: 2021 年预处理数据（6 栋建筑）+ 建筑信息表 + 事件调度表

---

## 2. 核心实体识别

基于数据内容，识别出以下 **7 类核心实体**，可作为图谱节点类型：

| 实体类型 | 说明 | 唯一标识示例 | 数量 |
|---|---|---|---|
| **Dataset** | 数据集本身 | `SHIFDR-Michigan` | 1 |
| **Building** | 商业建筑（以湖泊名匿名化） | `Aral`, `Victoria` | 14（本子集6） |
| **AirHandler** | 空气处理机组（AHU/RTU） | `Aral-AH1`, `Caspian-RTU1` | 17 |
| **Room** | 监测区域/房间 | `Aral-AH1-RM1` | 39 |
| **Fan** | 风机（送风/回风） | `Aral-AH1-SF`, `Michigan-AH4-RF` | 28 |
| **DR_Event** | 需求响应事件 | `2100001` | 90 |
| **MeasurementPoint** | BAS测点 | `Victoria-AH1-DA-TEMP` | ~250+ |

### 2.1 Building（建筑）

14栋建筑的核心属性：

| 建筑 | 编号 | 建造年份 | 面积(sq ft) | 年能耗(MWh) | 冷机位置 | 测量AHU数 | DR实验年份 |
|---|---|---|---|---|---|---|---|
| Aral | 00 | 2007 | 97,637 | 1,075 | 离站 | 3 | 2019-2021 |
| Baikal | 01 | 1985 | 76,731 | 1,294 | 离站 | 3 | 2019 |
| Caspian | 02 | 2006 | 59,825 | 508 | 离站 | 1 | 2019-2021 |
| Erie | 03 | 1955 | 45,452 | 3,292 | 离站 | 1 | 2019, 2020 |
| Huron | 04 | 2010 | 288,357 | 3,979 | 离站 | 5 | 2019-2021 |
| Ladoga | 05 | 1997 | 82,855 | 1,288 | 离站 | 5 | 2019 |
| Malawi | 06 | 1941 | 210,906 | 5,208 | 离站 | 5 | 2019, 2020 |
| Michigan | 07 | 1938 | 157,957 | 972 | 离站 | 4 | 2017-2021 |
| Ontario | 08 | 2007 | 97,637 | 1,075 | 离站 | 2 | 2019, 2020 |
| Superior | 09 | 2005 | 104,132 | 3,160 | 离站 | 3 | 2017-2021 |
| Titicaca | 10 | 1965 | 226,082 | 3,030 | 离站 | 5 | 2019, 2020 |
| Victoria | 11 | 1901 | 117,148 | 1,595 | 离站 | 2 | 2019-2021 |
| Vostok | 12 | 2006 | 85,000 | 1,030 | 在站 | 2 | 2017 |
| Winnipeg | 13 | 1994 | 143,450 | 1,613 | 离站 | 6 | 2019, 2020 |

**关键洞察**：
- 建筑面积跨度极大：45K–288K sq ft
- 年能耗与面积不成正比（如 Caspian 面积中等但能耗最低 508 MWh）
- 除 Vostok 外，所有建筑冷机均为离站设置（共享区域冷却站）
- Aral 和 Ontario 共享电表（同一栋建筑的不同区域）

### 2.2 AirHandler（空气处理机组）

2021年6栋建筑的AHU/RTU分布：

| 建筑 | 机组类型 | 机组编号 | 送风风机 | 回风风机 |
|---|---|---|---|---|
| Victoria | AHU | AH1, AH2, AH3 | AH1-SF, AH2-SF | AH2-RF, AH3-RF |
| Caspian | RTU | RTU1 | RTU1-SF | RTU1-RF |
| Michigan | AHU | AH1, AH2, AH3, AH4 | 4台SF | 4台RF |
| Superior | AHU | AH1, AH2, AH3 | 3台SF | 3台RF |
| Huron | AHU | AH1, AH2 | 2台SF | 2台RF |
| Aral | AHU | AH1, AH2, AH3 | 3台SF | 3台RF |

**关键洞察**：
- Caspian 使用 RTU（屋顶机组）而非 AHU，结构更简单
- Victoria 的 AH1/AH3 缺少回风风机功率（可能未独立计量或共管）
- Superior 额外有排风机（EXF）和冷水功率（CHW POW）

### 2.3 Room（房间/监测区域）

AHU→房间的隶属关系（从BAS列名推导）：

| 建筑 | AHU | 服务房间 |
|---|---|---|
| **Michigan** | AH1→RM1, AH2→RM2, AH3→RM3/RM4, AH4→RM5 |
| **Superior** | AH1→RM1/RM2/RM3, AH2→RM4/RM5/RM6/RM7, AH3→RM8/RM9/RM10 |
| **Huron** | AH1→RM1/RM5/RM6/RM8, AH2→RM2/RM3/RM4/RM7 |
| **Aral** | AH1→RM1/RM2/RM3, AH2→RM4/RM5/RM6, AH3→RM7/RM8/RM9 |
| **Caspian** | RTU1→RM2/RM3/RM4/RM5/RM6/RM7/RM8/RM9 |
| **Victoria** | 房间未明确归属AHU（RM1-RM4） |

**关键洞察**：
- 不同建筑的AHU服务房间数量差异大：1–4间/AHU
- Victoria 的房间测点无AHU前缀，可能是多AHU混合供区
- Superior 的 AH2 服务 4 个房间，负荷最大

### 2.4 DR_Event（需求响应事件）

2021年共 **90 个 DR 事件**：

| 属性 | 详情 |
|---|---|
| 时间范围 | 2021-07-27 ~ 2021-09-30 |
| 频次 | 每个实验日 3 次（9:00, 12:00, 15:00） |
| 时长 | 均为 1 小时 |
| 实验日数 | 30 天 |

**事件类型分布**：

| 类型 | 数量 | 含义 | 功率变化模式 |
|---|---|---|---|
| UD | 38 | 先上后下 | 功率先升后降（温度设定点先降后升） |
| DU | 37 | 先下后上 | 功率先降后升（温度设定点先升后降） |
| U | 8 | 仅上 | 功率仅上升（温度设定点下降） |
| D | 7 | 仅下 | 功率仅下降（温度设定点上升） |

**温度设定点调整幅度**：
- Up Change（设定点上调）: 0–2.0°F
- Down Change（设定点下调）: 0–1.5°F
- 双向事件中两个阶段等长（各30分钟）

### 2.5 MeasurementPoint（测点）

测点按物理量分类：

| 测点类型 | 含义 | 单位 | 出现频率 |
|---|---|---|---|
| TEMP | 温度 | °F | 130+ |
| CFM | 风量 | CFM 或 KCFM | 50+ |
| POS | 阀门/风门位置 | % | 23 |
| STPT | 温度设定点 | °F | 17 |
| HUM | 相对湿度 | % | 18 |
| DMPR | 风门开度 | % | 17 |
| FLOW | 水流量 | GPM | 10 |
| SP / DUCT SP | 静压 | in. w.c. | 11 |
| VP | 速度压力 | in. w.c. | 6 |
| LOAD/TON | 负荷/冷吨 | tons | 5 |
| BTU | 热量 | BTU | 2 |

---

## 3. 核心关系识别

以下关系可作为图谱的 **边类型**：

### 3.1 空间/设备层级关系

| 关系 | 源→目标 | 语义 |
|---|---|---|
| `HAS_AIR_HANDLER` | Building → AirHandler | 建筑包含空气处理机组 |
| `SERVES_ROOM` | AirHandler → Room | 机组服务的区域 |
| `HAS_SUPPLY_FAN` | AirHandler → Fan(SF) | 机组配置送风风机 |
| `HAS_RETURN_FAN` | AirHandler → Fan(RF) | 机组配置回风风机 |
| `HAS_MEASUREMENT` | Room → MeasurementPoint | 区域的监测测点 |
| `HAS_MEASUREMENT` | AirHandler → MeasurementPoint | 机组的监测测点 |

### 3.2 系统连接关系

| 关系 | 源→目标 | 语义 |
|---|---|---|
| `COOLED_BY` | AirHandler → ChilledWaterSystem | 机组由冷水系统供冷 |
| `HEATED_BY` | AirHandler → HotWaterSystem | 机组由热水系统供热 |
| `CONNECTED_TO` | Building → OffsiteChiller | 建筑使用离站冷机 |
| `SHARES_METER` | Building → Building | 共享电表（Aral↔Ontario） |

### 3.3 实验关系

| 关系 | 源→目标 | 语义 |
|---|---|---|
| `CONDUCTED_IN` | DR_Event → Building | 事件发生在哪栋建筑 |
| `AFFECTS` | DR_Event → AirHandler | 事件影响哪些机组 |
| `MEASURED_DURING` | MeasurementPoint → DR_Event | 事件期间的测点数据 |
| `PART_OF` | Dataset → Building | 建筑属于某数据集 |

### 3.4 数据时间关系

| 关系 | 源→目标 | 语义 |
|---|---|---|
| `DATA_AVAILABLE` | Building → Year | 某类数据的可用年份 |
| `EXPERIMENTED_IN` | Building → Year | DR实验年份 |

---

## 4. 数据层级结构

图谱应反映的层级：

```
Dataset: SHIFDR-Michigan
├── Building: Aral (Index:00)
│   ├── AirHandler: AH1
│   │   ├── Fan: AH1-SF (Supply Fan)
│   │   ├── Fan: AH1-RF (Return Fan)
│   │   ├── Room: RM1, RM2, RM3
│   │   └── MeasurementPoints: DA-TEMP, RA-TEMP, SA-TEMP, MA-TEMP, ...
│   ├── AirHandler: AH2
│   │   ├── Fan: AH2-SF, AH2-RF
│   │   ├── Room: RM4, RM5, RM6
│   │   └── MeasurementPoints: ...
│   ├── AirHandler: AH3
│   │   ├── Fan: AH3-SF, AH3-RF
│   │   ├── Room: RM7, RM8, RM9
│   │   └── MeasurementPoints: ...
│   ├── ChilledWaterSystem
│   │   └── MeasurementPoints: CHW-FLOW, CHWR-TEMP, CHWS-TEMP
│   ├── HotWaterSystem
│   │   └── MeasurementPoints: HTW-FLOW, HTWR-TEMP, HTWS-TEMP
│   └── DR_Events: 2100001, 2100002, ... (共90个)
├── Building: Victoria (Index:11)
│   └── ...
└── EventSchedule: 2021 (90 events)
```

---

## 5. 关键数据洞察

### 5.1 DR事件对风扇功率的影响

| 建筑 | DR事件期间均值(W) | 正常期间均值(W) | 差异(W) | 变化率 |
|---|---|---|---|---|
| Victoria | 29,361 | 18,201 | +11,160 | +61.3% |
| Caspian | 16,345 | 6,932 | +9,413 | +135.8% |
| Michigan | 23,234 | 14,341 | +8,893 | +62.0% |
| Superior | 37,391 | 27,125 | +10,266 | +37.8% |
| Huron | 27,747 | 15,206 | +12,541 | +82.5% |
| Aral | 31,744 | 22,131 | +9,613 | +43.4% |

**洞察**：
- Caspian 的 DR 响应最剧烈（+135.8%），可能与其较小的基准功率和单一 RTU 结构有关
- Superior 响应最温和（+37.8%），建筑体量大、3台AHU均摊了响应
- 所有建筑 DR 期间功率均显著上升，这是因为 DR 通过降低温度设定点增加制冷负荷，风扇功率随之上升

### 5.2 风扇功率规模差异

| 建筑 | FAN TOT POW 均值(W) | 最大值(W) | 标准差 | 风机数量 |
|---|---|---|---|---|
| Victoria | 18,759 | 61,478 | 10,792 | 3 (1SF+2SF+1RF) |
| Caspian | 7,403 | 53,970 | 10,454 | 2 (1SF+1RF) |
| Michigan | 14,785 | 50,592 | 10,641 | 8 (4SF+4RF) |
| Superior | 27,639 | 111,225 | 15,843 | 7 (3SF+3RF+1EXF) |
| Huron | 15,833 | 60,183 | 14,347 | 4 (2SF+2RF) |
| Aral | 22,612 | 76,142 | 11,681 | 6 (3SF+3RF) |

**洞察**：
- Superior 的总风扇功率最大，峰值超过 111kW
- 不同建筑的 SF/RF 功率比差异大：Aral 的 AH2-SF 均值(8549W) 远高于 AH2-RF(1815W)
- 送风风机(SF)普遍功率大于回风风机(RF)

### 5.3 建筑能耗特征

- **能耗密度**（年MWh/sq ft）差异显著：
  - Erie: 3292/45452 = 0.0724（最高）
  - Caspian: 508/59825 = 0.0085（最低）
  - 相差近 8.5 倍
- **建筑年龄 vs 能耗**：无明显线性关系，老建筑(Erie, 1955)能耗密度反而高
- **面积 vs 风机数量**：大体量建筑(Huron, 288K sq ft)配有更多AHU(5台)

### 5.4 BAS测点分布特征

- 温度(TEMP)是最普遍的测点类型，每栋建筑 13–27 个
- Superior 独有大量速度压力(VP)和静压(SP)测点
- Caspian 独有冷吨/负荷(TON/LOAD)和热量(BTU)测点
- 室外环境(OA)仅在 Victoria 和 Superior 中直接测量

---

## 6. 数据质量与边界

### 6.1 数据缺失

- 部分建筑的 BAS 数据年份不完整（如 Baikal 仅 2019 年有 BAS 数据）
- Ladoga 无 BAS 数据（标注 N/A）
- 某些AHU的回风风机功率值为0（可能未独立计量）

### 6.2 匿名化

- 建筑名称以湖泊名替换（保护隐私）
- BAS 测点标签已匿名化（如房间编号 RM1 并非实际房间号）
- 但 HVAC 缩写体系保持一致（AH, SF, RF, CHW 等）

### 6.3 数据范围

- 当前子集仅包含 **2021年预处理数据**（6栋建筑）
- 完整数据集有 14 栋建筑 + 2017-2021 全年原始数据（824 MB）
- 2021 数据时间范围：2021-07-19 ~ 2021-10-01，1分钟分辨率，每栋建筑 108,000 行

---

## 7. 图谱提取建议

### 7.1 推荐节点类型与属性

```
(:Dataset {
  id, name, doi, license, funding, description, 
  total_buildings, total_files, total_size_mb
})

(:Building {
  id, name, index, construction_year, square_footage, 
  annual_energy_mwh, chiller_location, num_ahus_measured,
  fan_voltage, bas_manufacturer, data_years, experiment_years
})

(:AirHandler {
  id, building_name, handler_id, type  // AHU or RTU
})

(:Fan {
  id, building_name, handler_id, fan_type,  // SF or RF
  mean_power_w, max_power_w, min_power_w, stdev_power_w
})

(:Room {
  id, building_name, room_id, served_by_handler
})

(:ChilledWaterSystem {
  id, building_name, location  // onsite or offsite
})

(:HotWaterSystem {
  id, building_name
})

(:DR_Event {
  id, event_id, date, start_time, end_time, 
  type, up_change_f, down_change_f, duration_min
})

(:MeasurementPoint {
  id, building_name, handler_id, room_id, 
  measurement_type, physical_quantity, unit
})
```

### 7.2 推荐边类型

```
(:Building)-[:HAS_AIR_HANDLER]->(:AirHandler)
(:Building)-[:HAS_CHW_SYSTEM]->(:ChilledWaterSystem)
(:Building)-[:HAS_HW_SYSTEM]->(:HotWaterSystem)
(:Building)-[:PART_OF_DATASET]->(:Dataset)
(:Building)-[:SHARES_METER_WITH]->(:Building)
(:AirHandler)-[:SERVES_ROOM]->(:Room)
(:AirHandler)-[:HAS_FAN]->(:Fan)
(:AirHandler)-[:HAS_MEASUREMENT]->(:MeasurementPoint)
(:Room)-[:HAS_MEASUREMENT]->(:MeasurementPoint)
(:ChilledWaterSystem)-[:HAS_MEASUREMENT]->(:MeasurementPoint)
(:DR_Event)-[:CONDUCTED_IN]->(:Building)
(:Fan)-[:POWER_MEASURED_IN]->(:MeasurementPoint)
```

### 7.3 可提取的量化关系

| 关系 | 来源 | 示例 |
|---|---|---|
| DR功率响应率 | DR事件 vs 正常功率 | Caspian: +135.8% |
| 风机功率占比 | 单风机 / 总风机功率 | Aral AH2-SF: 37.8% |
| 能耗密度 | 年能耗 / 面积 | Erie: 0.0724 MWh/sq ft |
| AHU服务房间数 | count(SERVES_ROOM) | Superior AH2: 4 rooms |
| 测点覆盖度 | 测点数 / AHU数 | Michigan: 69列/4 AHU |

---

## 8. 文件与数据映射

| 文件 | 映射到的图谱实体 |
|---|---|
| `README.txt` | Dataset 描述、方法论、缩写词表 |
| `BuildingInformation.csv` | Building 节点及全部属性 |
| `j6731449j_metadata_report.txt` | Dataset 元数据（DOI、作者、资助方） |
| `2021_Event_Schedule.csv` | DR_Event 节点（90个） |
| `Victoria.csv` | Victoria 建筑的 Fan功率 + MeasurementPoint 时序 |
| `Caspian.csv` | Caspian 建筑的 Fan功率 + MeasurementPoint 时序 |
| `Michigan.csv` | Michigan 建筑的 Fan功率 + MeasurementPoint 时序 |
| `Superior.csv` | Superior 建筑的 Fan功率 + MeasurementPoint 时序 |
| `Huron.csv` | Huron 建筑的 Fan功率 + MeasurementPoint 时序 |
| `Aral.csv` | Aral 建筑的 Fan功率 + MeasurementPoint 时序 |

---

*报告生成时间: 2026-06-13*
*数据版本: SHIFDR Michigan Buildings Dataset, 2023-05-22*
