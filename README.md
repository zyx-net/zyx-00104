# 设备校准证书接收与放行服务

基于 Flask 的本地 JSON API 服务，用于管理设备校准证书的接收、校验、审批和放行流程。

## 功能特性

- 支持 JSON/CSV 格式证书导入
- 完整的数据校验（设备编号、日期、有效期、量程、单位、偏差值）
- 自动化工作流程：录入 → 计量员复核 → 主管批准 → 放行/限用/停用
- 严格的错误处理：日期倒挂、设备不匹配、偏差超阈值、权限校验
- 完整的审计日志：操作者、备注、决策依据、版本记录
- 数据持久化：SQLite 数据库，确保服务重启后数据一致
- 导出功能：支持按设备或批次导出 JSON/CSV

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
flask init-db
```

或者直接运行应用，数据库会自动创建。

### 3. 启动服务

```bash
python app.py
```

服务将在 http://localhost:5000 运行。

## API 端点

### 健康检查

```bash
curl http://localhost:5000/api/health
```

### 设备管理

#### 创建设备
```bash
curl -X POST http://localhost:5000/api/equipment \
  -H "Content-Type: application/json" \
  -d @samples/equipment.json
```

#### 导入设备清单（批量）
```bash
curl -X POST http://localhost:5000/api/equipment \
  -H "Content-Type: application/json" \
  -d '[
    {
      "equipment_no": "EQ-2024-001",
      "equipment_name": "Digital Multimeter",
      "model_spec": "FLUKE 87V",
      "manufacturer": "Fluke Corporation",
      "range_min": 0,
      "range_max": 1000,
      "unit": "V",
      "tolerance": 0.05,
      "location": "Lab A"
    }
  ]'
```

#### 查看所有设备
```bash
curl http://localhost:5000/api/equipment
```

#### 查看单个设备
```bash
curl http://localhost:5000/api/equipment/1
```

### 证书导入

#### JSON 格式导入
```bash
curl -X POST http://localhost:5000/api/certificates/import \
  -H "Content-Type: application/json" \
  -d @samples/certificates_valid.json
```

#### CSV 格式导入
```bash
curl -X POST http://localhost:5000/api/certificates/import/csv \
  -F "file=@samples/certificates.csv" \
  -F "operator=Zhang San" \
  -F "batch_id=BATCH-2024-001"
```

#### 单个证书导入
```bash
curl -X POST http://localhost:5000/api/certificates/import \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Zhang San",
    "batch_id": "BATCH-2024-002",
    "data": [
      {
        "cert_no": "CERT-2024-001",
        "equipment_no": "EQ-2024-001",
        "calibration_date": "2024-06-01",
        "valid_until": "2025-06-01",
        "range_min": 0,
        "range_max": 1000,
        "unit": "V",
        "deviation": 0.02,
        "calibrator": "Zhang San"
      }
    ]
  }'
```

### 证书查询

#### 查看所有证书
```bash
curl http://localhost:5000/api/certificates
```

#### 按工作流状态筛选
```bash
curl "http://localhost:5000/api/certificates?workflow_status=draft"
```

#### 按设备筛选
```bash
curl "http://localhost:5000/api/certificates?equipment_id=1"
```

#### 按批次筛选
```bash
curl "http://localhost:5000/api/certificates?batch_id=BATCH-2024-001"
```

#### 查看单个证书
```bash
curl http://localhost:5000/api/certificates/1
```

### 工作流程操作

#### 1. 录入（Entry）
```bash
curl -X POST http://localhost:5000/api/certificates/1/enter \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Operator1",
    "notes": "Certificate data entered and verified"
  }'
```

#### 2. 计量员复核（Review）
```bash
curl -X POST http://localhost:5000/api/certificates/1/review \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Metrologist1",
    "notes": "Technical review completed",
    "decision_basis": "All parameters within specification"
  }'
```

#### 3. 主管批准（Approve）
```bash
curl -X POST http://localhost:5000/api/certificates/1/approve \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor1",
    "notes": "Approved for release",
    "decision_basis": "Meets quality standards"
  }'
```

#### 4. 放行（Release）
```bash
curl -X POST http://localhost:5000/api/certificates/1/release \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Operator2",
    "notes": "Device cleared for use",
    "decision_basis": "All checks passed"
  }'
```

#### 限用（Limit）
```bash
curl -X POST http://localhost:5000/api/certificates/1/limit \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor1",
    "notes": "Limited to specific range",
    "decision_basis": "Deviation in upper range"
  }'
```

#### 停用（Stop）
```bash
curl -X POST http://localhost:5000/api/certificates/1/stop \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor1",
    "notes": "Device decommissioned",
    "decision_basis": "Failed accuracy requirements"
  }'
```

### 审计日志

#### 查看所有审计记录
```bash
curl http://localhost:5000/api/audit
```

#### 按证书筛选
```bash
curl "http://localhost:5000/api/audit?certificate_id=1"
```

#### 按操作者筛选
```bash
curl "http://localhost:5000/api/audit?operator=Metrologist1"
```

#### 按批次筛选
```bash
curl "http://localhost:5000/api/audit?batch_id=BATCH-2024-001"
```

### 数据导出

#### 按设备导出 JSON
```bash
curl "http://localhost:5000/api/export/equipment/1" > equipment_1_certs.json
```

#### 按设备导出 CSV
```bash
curl "http://localhost:5000/api/export/equipment/1?format=csv" > equipment_1_certs.csv
```

#### 按批次导出 JSON
```bash
curl "http://localhost:5000/api/export/batch/BATCH-2024-001" > batch_certs.json
```

#### 按批次导出 CSV
```bash
curl "http://localhost:5000/api/export/batch/BATCH-2024-001?format=csv" > batch_certs.csv
```

#### 导出所有证书
```bash
curl "http://localhost:5000/api/export/all" > all_certs.json
```

### 批量操作

#### 批量审批
```bash
curl -X POST http://localhost:5000/api/certificates/batch/approve \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Supervisor1",
    "certificate_ids": [1, 2, 3],
    "notes": "Batch approval",
    "decision_basis": "All certificates meet quality standards"
  }'
```

响应示例（混合结果 - 部分成功部分失败）：
```json
{
  "total": 3,
  "successful": 2,
  "failed": 1,
  "results": [
    {"certificate_id": 1, "cert_no": "CERT-001", "success": true, "workflow_status": "approved"},
    {"certificate_id": 2, "cert_no": "CERT-002", "success": true, "workflow_status": "approved"},
    {
      "certificate_id": 3,
      "cert_no": "CERT-003",
      "success": false,
      "errors": [{"error": "Invalid transition from draft to approved", "field": "workflow_status"}]
    }
  ]
}
```

#### 批量放行
```bash
curl -X POST http://localhost:5000/api/certificates/batch/release \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Operator2",
    "certificate_ids": [1, 2, 3],
    "notes": "Batch release",
    "decision_basis": "All checks passed"
  }'
```

响应示例（包含权限检查失败）：
```json
{
  "total": 3,
  "successful": 1,
  "failed": 2,
  "results": [
    {"certificate_id": 1, "cert_no": "CERT-001", "success": true, "workflow_status": "released"},
    {
      "certificate_id": 2,
      "cert_no": "CERT-002",
      "success": false,
      "errors": [{"error": "Operator cannot release their own entry", "field": "operator"}]
    },
    {
      "certificate_id": 3,
      "cert_no": "CERT-003",
      "success": false,
      "errors": [{"error": "Invalid transition from draft to released", "field": "workflow_status"}]
    }
  ]
}
```

#### 批量操作特点
- **非原子性**：每个证书独立处理，一个失败不影响其他
- **权限检查**：放行时检查操作人是否为录入人
- **状态验证**：只有处于审批通过(approved)状态的证书才能放行

### 操作撤销

#### 撤销最近工作流变更
```bash
curl -X POST http://localhost:5000/api/certificates/1/revert \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Admin1",
    "notes": "Revert due to incorrect approval"
  }'
```

响应示例：
```json
{
  "id": 1,
  "cert_no": "CERT-001",
  "workflow_status": "reviewed",
  "approved_by": null,
  "approved_at": null,
  "version": 5,
  ...
}
```

#### 撤销限制
- 只能撤销最近一次工作流变更
- 已撤销的变更不能再次撤销
- 撤销会恢复：
  - 证书工作流状态
  - 相关人员信息（approved_by, released_by 等）
  - 设备状态（如果是 release/limit/stop 操作）
- 撤销操作本身会记录审计日志

#### 重复撤销失败示例
```bash
# 第一次撤销成功
curl -X POST http://localhost:5000/api/certificates/1/revert \
  -H "Content-Type: application/json" \
  -d '{"operator": "Admin1", "notes": "First revert"}'

# 第二次撤销失败
curl -X POST http://localhost:5000/api/certificates/1/revert \
  -H "Content-Type: application/json" \
  -d '{"operator": "Admin1", "notes": "Second revert"}'

# 响应：
{
  "errors": [
    {"error": "No workflow change to revert"}
  ]
}
```

#### 撤销草稿状态失败示例
```bash
curl -X POST http://localhost:5000/api/certificates/1/revert \
  -H "Content-Type: application/json" \
  -d '{"operator": "Admin1", "notes": "Try to revert draft"}'

# 响应：
{
  "errors": [
    {"error": "No workflow change to revert"}
  ]
}
```

## 错误处理示例

### 1. 日期倒挂错误
```bash
curl -X POST http://localhost:5000/api/certificates/import \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Zhang San",
    "data": [
      {
        "cert_no": "CERT-2024-ERROR-001",
        "equipment_no": "EQ-2024-001",
        "calibration_date": "2025-07-01",
        "valid_until": "2025-06-01",
        "range_min": 0,
        "range_max": 1000,
        "unit": "V",
        "deviation": 0.02
      }
    ]
  }'
```

响应：
```json
{
  "batch_id": "xxx",
  "total": 1,
  "successful": 0,
  "failed": 1,
  "errors": [
    {
      "index": 0,
      "cert_no": "CERT-2024-ERROR-001",
      "errors": [
        {
          "field": "valid_until",
          "error": "Valid until date must be after calibration date: 2025-06-01 <= 2025-07-01"
        }
      ]
    }
  ],
  "imported": []
}
```

### 2. 设备不匹配错误
```bash
curl -X POST http://localhost:5000/api/certificates/import \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Zhang San",
    "data": [
      {
        "cert_no": "CERT-2024-ERROR-002",
        "equipment_no": "EQ-2024-999",
        "calibration_date": "2024-06-01",
        "valid_until": "2025-06-01",
        "range_min": 0,
        "range_max": 1000,
        "unit": "V",
        "deviation": 0.02
      }
    ]
  }'
```

响应：
```json
{
  "errors": [
    {
      "field": "equipment_no",
      "error": "Equipment EQ-2024-999 not found"
    }
  ]
}
```

### 3. 偏差超阈值错误
```bash
curl -X POST http://localhost:5000/api/certificates/import \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Zhang San",
    "data": [
      {
        "cert_no": "CERT-2024-ERROR-003",
        "equipment_no": "EQ-2024-001",
        "calibration_date": "2024-06-01",
        "valid_until": "2025-06-01",
        "range_min": 0,
        "range_max": 1000,
        "unit": "V",
        "deviation": 0.1
      }
    ]
  }'
```

响应：
```json
{
  "errors": [
    {
      "field": "deviation",
      "error": "Deviation 0.1 exceeds tolerance 0.05"
    }
  ]
}
```

### 4. 录入员尝试放行错误
```bash
curl -X POST http://localhost:5000/api/certificates/1/release \
  -H "Content-Type: application/json" \
  -d '{
    "operator": "Operator1"
  }'
```

响应：
```json
{
  "errors": [
    {
      "error": "Operator cannot release their own entry",
      "field": "operator"
    }
  ],
  "message": "Release failed"
}
```

## 工作流程状态

```
DRAFT → ENTERED → REVIEWED → APPROVED → RELEASED/LIMITED/STOPPED
```

- **DRAFT**: 草稿状态，证书刚导入
- **ENTERED**: 已录入，数据录入员确认
- **REVIEWED**: 已复核，计量员审核通过
- **APPROVED**: 已批准，主管审批通过
- **RELEASED**: 已放行，设备可正常使用
- **LIMITED**: 限用，设备在限制条件下使用
- **STOPPED**: 停用，设备不可使用

## 数据一致性保证

1. **事务处理**: 所有导入操作使用数据库事务，失败时自动回滚
2. **原子性**: 批量导入要么全部成功，要么全部失败，不留半条记录
3. **持久化**: 使用 SQLite 数据库，服务重启后数据不丢失
4. **幂等性**: 相同批次号再次导入会检测重复证书号，防止重复导入
5. **版本控制**: 每次状态变更都会增加版本号，保留历史记录

## 审计日志字段

- `timestamp`: 操作时间
- `operator`: 操作者
- `action`: 操作类型（import, enter, review, approve, release, limit, stop, revert）
- `resource_type`: 资源类型（equipment, certificate）
- `resource_id`: 资源ID
- `notes`: 备注
- `decision_basis`: 决策依据
- `version`: 版本号
- `previous_state`: 前一个状态
- `new_state`: 新状态
- `reverted`: 是否已被撤销
- `reverted_by`: 撤销操作人
- `reverted_at`: 撤销时间
- `revert_log_id`: 关联的撤销日志ID

## 目录结构

```
.
├── app.py                  # 主应用文件
├── models.py               # 数据模型
├── services.py             # 业务逻辑层
├── validators.py           # 数据校验
├── requirements.txt        # 依赖列表
├── calibration.db          # SQLite 数据库（自动生成）
├── samples/
│   ├── equipment.json      # 设备清单样例
│   ├── certificates_valid.json    # 有效证书样例
│   ├── certificates_errors.json  # 错误证书样例
│   └── certificates.csv    # CSV 格式证书样例
└── README.md              # 本文档
```

## 测试建议

1. 先导入设备清单
2. 导入有效证书，确认成功
3. 导入错误证书，确认校验失败
4. 完整执行工作流程：录入→复核→批准→放行
5. 查看审计日志，确认记录完整
6. 导出数据，验证格式正确
