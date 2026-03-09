# Live2D Hiyori 模型开发指南

本文档详细说明 Live2D Hiyori 模型的文件结构和接口，用于指导开发。

---

## 一、文件结构

```
live2d/
├── Hiyori.model3.json      # 主配置文件（必需）
├── Hiyori.cdi3.json       # 参数显示信息（必需）
├── Hiyori.pose3.json      # 姿势配置（必需）
├── Hiyori.physics3.json    # 物理模拟配置（必需）
├── Hiyori.userdata3.json   # 用户数据（必需）
├── Hiyori.moc3           # 模型数据（二进制，必需）
├── Hiyori.2048/           # 纹理贴图文件夹
│   ├── texture_00.png
│   └── texture_01.png
└── motions/               # 动作文件
    ├── Hiyori_m01.motion3.json
    ├── Hiyori_m02.motion3.json
    └── ...
```

---

## 二、主要配置文件详解

### 1. Hiyori.model3.json - 主模型定义

这是最核心的配置文件，定义了模型的基本结构和动作引用。

```json
{
  "Version": 3,
  "FileReferences": {
    "Moc": "Hiyori.moc3",
    "Textures": ["Hiyori.2048/texture_00.png", "Hiyori.2048/texture_01.png"],
    "Physics": "Hiyori.physics3.json",
    "Pose": "Hiyori.pose3.json",
    "UserData": "Hiyori.userdata3.json",
    "DisplayInfo": "Hiyori.cdi3.json",
    "Motions": {
      "Idle": [
        {"File": "motions/Hiyori_m01.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5},
        {"File": "motions/Hiyori_m02.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5}
      ],
      "TapBody": [
        {"File": "motions/Hiyori_m04.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5}
      ]
    }
  },
  "Groups": [
    {"Target": "Parameter", "Name": "LipSync", "Ids": ["ParamMouthOpenY"]},
    {"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen", "ParamEyeROpen"]}
  ],
  "HitAreas": [
    {"Id": "HitArea", "Name": "Body"}
  ]
}
```

**字段说明**：
- `Motions`: 动作分组，每组包含多个动作引用
- `Groups`: 参数分组，用于批量控制
- `HitAreas`: 点击检测区域

---

### 2. Hiyori.cdi3.json - 参数显示信息

定义所有参数的元数据信息，包括名称、分组等。

```json
{
  "Version": 3,
  "Parameters": [
    {"Id": "ParamAngleX", "GroupId": "ParamGroupFace", "Name": "角度 X"},
    {"Id": "ParamAngleY", "GroupId": "ParamGroupFace", "Name": "角度 Y"},
    {"Id": "ParamMouthOpenY", "GroupId": "ParamGroupMouth", "Name": "口 開閉"}
  ],
  "ParameterGroups": [
    {"Id": "ParamGroupFace", "Name": "顔"},
    {"Id": "ParamGroupEyes", "Name": "目"},
    {"Id": "ParamGroupMouth", "Name": "口"}
  ],
  "Parts": [
    {"Id": "PartEye", "Name": "目"},
    {"Id": "PartMouth", "Name": "口"}
  ]
}
```

---

### 3. Hiyori.pose3.json - 姿势配置

定义部件之间的联动关系。

```json
{
  "Type": "Live2D Pose",
  "FadeInTime": 0.5,
  "Groups": [
    {
      "Id": "PartArmA",
      "Link": []  // 联动的部件 ID
    },
    {
      "Id": "PartArmB",
      "Link": []
    }
  ]
}
```

---

### 4. Hiyori.physics3.json - 物理模拟配置

定义头发、丝带、裙子等部件的物理效果。

```json
{
  "Version": 3,
  "Meta": {
    "PhysicsSettingCount": 11,
    "TotalInputCount": 34,
    "TotalOutputCount": 35,
    "VertexCount": 58
  },
  "EffectiveForces": {
    "Gravity": {"X": 0, "Y": -1},
    "Wind": {"X": 0, "Y": 0}
  },
  "PhysicsDictionary": [
    {"Id": "PhysicsSetting1", "Name": "前髪"},
    {"Id": "PhysicsSetting2", "Name": "後ろ髪"}
  ],
  "PhysicsSettings": [
    {
      "Id": "PhysicsSetting1",
      "Input": [
        {
          "Source": {"Target": "Parameter", "Id": "ParamAngleX"},
          "Weight": 60,
          "Type": "X",
          "Reflect": false
        }
      ],
      "Output": [
        {
          "Destination": {"Target": "Parameter", "Id": "ParamHairFront"},
          "VertexIndex": 1,
          "Scale": 1.522,
          "Weight": 100,
          "Type": "Angle",
          "Reflect": false
        }
      ],
      "Vertices": [
        {
          "Position": {"X": 0, "Y": 0},
          "Mobility": 1,
          "Delay": 1,
          "Acceleration": 1,
          "Radius": 0
        }
      ],
      "Normalization": {
        "Position": {"Minimum": -10, "Default": 0, "Maximum": 10},
        "Angle": {"Minimum": -10, "Default": 0, "Maximum": 10}
      }
    }
  ]
}
```

---

### 5. Hiyori.userdata3.json - 用户数据

存储自定义数据，用于标记某些部件状态。

```json
{
  "Version": 3,
  "Meta": {"UserDataCount": 7, "TotalUserDataSize": 35},
  "UserData": [
    {"Target": "ArtMesh", "Id": "ArtMesh93", "Value": "ribon"},
    {"Target": "ArtMesh", "Id": "ArtMesh94", "Value": "ribon"}
  ]
}
```

---

## 三、动作文件详解

### motions/*.motion3.json - 动作文件

每个文件定义一个完整的动画序列。

```json
{
  "Version": 3,
  "Meta": {
    "Duration": 4.7,      // 动作时长（秒）
    "Fps": 30.0,         // 帧率
    "Loop": true,         // 是否循环
    "AreBeziersRestricted": false,
    "CurveCount": 31,
    "TotalSegmentCount": 135,
    "TotalPointCount": 374,
    "UserDataCount": 0,
    "TotalUserDataSize": 0
  },
  "Curves": [
    {
      "Target": "Parameter",  // 或 "PartOpacity"
      "Id": "ParamAngleX",
      "Segments": [0, -8, 1, 0.067, -8, 0.133, -8, ...]
    }
  ]
}
```

**Segments 数组格式**：
```
[step_count, time1, value1, time2, value2, ..., step_count]
```

---

## 四、可用参数列表

### 面部参数
| 参数 ID | 中文名 | 值域 |
|--------|--------|------|
| `ParamAngleX` | 面部 X 轴角度 | [-30, 30] |
| `ParamAngleY` | 面部 Y 轴角度 | [-30, 30] |
| `ParamAngleZ` | 面部 Z 轴角度 | [-30, 30] |
| `ParamCheek` | 脸颊/腮红 | [0, 1] |

### 眼睛参数
| 参数 ID | 中文名 | 值域 |
|--------|--------|------|
| `ParamEyeLOpen` | 左眼开闭 | [0, 1] (0=闭, 1=开) |
| `ParamEyeLSmile` | 左眼微笑 | [0, 1] |
| `ParamEyeROpen` | 右眼开闭 | [0, 1] (0=闭, 1=开) |
| `ParamEyeRSmile` | 右眼微笑 | [0, 1] |
| `ParamEyeBallX` | 眼球 X 方向 | [-1, 1] |
| `ParamEyeBallY` | 眼球 Y 方向 | [-1, 1] |

### 眉毛参数
| 参数 ID | 中文名 | 值域 |
|--------|--------|------|
| `ParamBrowLY` | 左眉上下 | [-1, 1] |
| `ParamBrowRY` | 右眉上下 | [-1, 1] |
| `ParamBrowLX` | 左眉左右 | [-1, 1] |
| `ParamBrowRX` | 右眉左右 | [-1, 1] |
| `ParamBrowLAngle` | 左眉角度 | [-1, 1] |
| `ParamBrowRAngle` | 右眉角度 | [-1, 1] |
| `ParamBrowLForm` | 左眉变形 | [0, 1] |
| `ParamBrowRForm` | 右眉变形 | [0, 1] |

### 嘴巴参数
| 参数 ID | 中文名 | 值域 |
|--------|--------|------|
| `ParamMouthForm` | 嘴巴变形 | [0, 1] |
| `ParamMouthOpenY` | 嘴巴开闭 | [0, 1] (用于嘴形同步) |

### 身体参数
| 参数 ID | 中文名 | 值域 |
|--------|--------|------|
| `ParamBodyAngleX` | 身体 X 轴旋转 | [-10, 10] |
| `ParamBodyAngleY` | 身体 Y 轴旋转 | [-10, 10] |
| `ParamBodyAngleZ` | 身体 Z 轴旋转 | [-10, 10] |
| `ParamBreath` | 呼吸 | [0, 1] |
| `ParamShoulder` | 肩膀耸动 | [-1, 1] |
| `ParamLeg` | 腿部 | [0, 1] |

### 手臂参数
| 参数 ID | 中文名 | 值域 |
|--------|--------|------|
| `ParamArmLA` | 左臂 A | [-10, 10] |
| `ParamArmRA` | 右臂 A | [-10, 10] |
| `ParamArmLB` | 左臂 B | [-10, 10] |
| `ParamArmRB` | 右臂 B | [-10, 10] |
| `ParamHandLB` | 左手 B 旋转 | [-10, 10] |
| `ParamHandRB` | 右手 B 旋转 | [-10, 10] |
| `ParamHandL` | 左手 | [-10, 10] |
| `ParamHandR` | 右手 | [-10, 10] |

### 摇摆参数
| 参数 ID | 中文名 | 值域 |
|--------|--------|------|
| `ParamBustY` | 胸部摇动 | [-3, 3] |
| `ParamHairAhoge` | 头发摇动-呆毛 | [-10, 10] |
| `ParamHairFront` | 头发摇动-前 | [-10, 10] |
| `ParamHairBack` | 头发摇动-后 | [-30, 30] |
| `ParamSideupRibbon` | 头饰摇动 | [-8, 8] |
| `ParamRibbon` | 胸前丝带摇动 | [-10.6, 10.6] |
| `ParamSkirt` | 裙子摇动 | [-10, 10] |
| `ParamSkirt2` | 裙子弯曲 | [-10, 10] |

---

## 五、可用动作

动作通过 `startMotion(group, index)` 播放。

### Idle 动作组（待机动作）
| 索引 | 文件 |
|------|------|
| 0 | motions/Hiyori_m01.motion3.json |
| 1 | motions/Hiyori_m02.motion3.json |
| 2 | motions/Hiyori_m03.motion3.json |
| 3 | motions/Hiyori_m05.motion3.json |
| 4 | motions/Hiyori_m06.motion3.json |
| 5 | motions/Hiyori_m07.motion3.json |
| 6 | motions/Hiyori_m08.motion3.json |
| 7 | motions/Hiyori_m09.motion3.json |
| 8 | motions/Hiyori_m10.motion3.json |

### TapBody 动作组（点击身体）
| 索引 | 文件 |
|------|------|
| 0 | motions/Hiyori_m04.motion3.json |

---

## 六、JavaScript 调用示例

```javascript
// 获取模型实例
const model = lappModel.getModel();

// 播放动作
model.startMotion("Idle", 0);           // 播放 Idle 组的第 0 个动作
model.startMotion("TapBody", 0);        // 播放 TapBody 动作

// 设置参数
model.setParameterValue("ParamMouthOpenY", 0.5);  // 张嘴
model.setParameterValue("ParamEyeLOpen", 0);      // 闭左眼
model.setParameterValue("ParamEyeBallX", 0.3);   // 眼球向右看
model.setParameterValue("ParamBodyAngleY", 10);   // 身体倾斜
```

---

## 七、动作定制方法

### 方法 1: 手动编写 motion3.json 文件

创建一个新动作文件 `motions/Hiyori_custom.motion3.json`：

```json
{
  "Version": 3,
  "Meta": {
    "Duration": 3.0,
    "Fps": 30,
    "Loop": false
  },
  "Curves": [
    {
      "Target": "Parameter",
      "Id": "ParamMouthOpenY",
      "Segments": [0, 0, 1, 0.5, 1, 0, 1, 0.5, 0]
    },
    {
      "Target": "Parameter",
      "Id": "ParamEyeLSmile",
      "Segments": [0, 0, 1, 1, 1]
    }
  ]
}
```

然后在 `Hiyori.model3.json` 中添加新动作组：

```json
"Motions": {
  "Idle": [...],
  "TapBody": [...],
  "CustomAction": [  // 新增动作组
    {
      "File": "motions/Hiyori_custom.motion3.json",
      "FadeInTime": 0.3,
      "FadeOutTime": 0.3
    }
  ]
}
```

### 方法 2: 使用 Live2D 编辑工具

推荐使用官方工具创建动作：

1. **Live2D Cubism Editor** - 官方编辑器，可录制和编辑动作
   - 下载：https://www.live2d.com/download/cubism-sdk-for-web
   - 支持：动作录制、参数调整、物理效果预览

2. **Live2D Viewer** - 预览模型和动作
   - 可视化查看模型效果
   - 测试动作播放

---

## 八、特殊参数组

| 组名 | 用途 | 包含参数 |
|------|------|----------|
| `LipSync` | 嘴形同步组 | `ParamMouthOpenY` |
| `EyeBlink` | 自动眨眼组 | `ParamEyeLOpen`, `ParamEyeROpen` |

---

## 九、动作数据示例

一个典型的点头动作示例：

```json
{
  "Version": 3,
  "Meta": {
    "Duration": 1.5,
    "Fps": 30,
    "Loop": false,
    "CurveCount": 2,
    "TotalSegmentCount": 4,
    "TotalPointCount": 4
  },
  "Curves": [
    {
      "Target": "Parameter",
      "Id": "ParamBodyAngleY",
      "Segments": [0, 0, 1, 10, 0.5, 0, 0.75, 0]
    },
    {
      "Target": "Parameter",
      "Id": "ParamAngleY",
      "Segments": [0, 0, 1, 5, 0.5, 0, 0.75, 0]
    }
  ]
}
```

**Segments 解析**：
- `0, 0, 1, 10` - 线性插值：时间 0-1 秒，值从 0 变到 10
- `0.5, 0, 0.75, 0` - 线性插值：时间 0.5-0.75 秒，值从 0 变到 0

---

## 十、常见问题

### Q1: 如何让动作循环播放？
A: 在动作文件的 `Meta` 中设置 `"Loop": true`

### Q2: 如何控制动作切换的平滑度？
A: 在 model3.json 中设置 `FadeInTime` 和 `FadeOutTime`（秒）

### Q3: 眼球方向参数怎么用？
A: `ParamEyeBallX` 控制左右，`ParamEyeBallY` 控制上下，值域 [-1, 1]

### Q4: 如何添加新的动作分组？
A: 在 `Hiyori.model3.json` 的 `Motions` 对象中添加新键

---

## 十一、资源链接

- **Live2D 官网**: https://www.live2d.com/
- **SDK 下载**: https://www.live2d.com/download/cubism-sdk-for-web
- **文档**: https://www.live2d.com/download/cubism-sdk-for-web
- **Hiyori 模型**: 由 Live2D 官方提供的示例模型
