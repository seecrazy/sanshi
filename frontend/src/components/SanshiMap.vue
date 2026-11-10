<script setup lang="ts">
// 轻量地图组件：Leaflet + 高德瓦片（免 key，中文标注）。
// 坐标策略：业务数据统一 WGS84 存储，显示时转 GCJ02（高德瓦片坐标系），迁移/换瓦片源见 docs/UNIAPP_MIGRATION.md §3。
import { onMounted, onUnmounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const props = defineProps<{
  merchant?: { lat: number; lng: number; name?: string } | null
  dest?: { lat: number; lng: number; text?: string } | null
  rider?: { lat: number | null; lng: number | null; name?: string } | null
}>()

const el = ref<HTMLElement | null>(null)
let map: L.Map | null = null
let markers: Record<string, L.Marker> = {}

// WGS84 -> GCJ02（国测局偏移，标准近似公式）
function wgs2gcj(lat: number, lng: number): [number, number] {
  const a = 6378245.0, ee = 0.00669342162296594323
  const dLat = (x: number) => {
    let ret = -100 + 2 * x + 3 * 0.0001 * x * x + 0.00000112 * x ** 3 + 0.0000043 * Math.PI / 180 * Math.sin(x * Math.PI * 300 / 180) * 2 / 3
    return ret
  }
  const dLng = (y: number) => {
    let ret = 300 + y + 2 * 0.0001 * y + 0.00000109 * y * y + 0.00000438 * Math.PI / 180 * Math.sin(y * Math.PI * 300 / 180) * 2 / 3
    return ret
  }
  let dLatV = dLat(lat * Math.PI / 180), dLngV = dLng(lng * Math.PI / 180)
  const radLat = lat / 180 * Math.PI
  let magic = Math.sin(radLat); magic = 1 - ee * magic * magic
  const sqrtMagic = Math.sqrt(magic)
  dLatV = (dLatV * 180) / ((a * (1 - ee)) / (magic * sqrtMagic) * Math.PI)
  dLngV = (dLngV * 180) / (a / sqrtMagic * Math.cos(radLat) * Math.PI)
  return [lat + dLatV, lng + dLngV]
}

function dotIcon(color: string, label: string) {
  return L.divIcon({
    className: '',
    html: `<div style="width:26px;height:26px;border-radius:50%;background:${color};border:3px solid #fff;
      box-shadow:0 1px 6px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;
      color:#fff;font-size:11px;font-weight:700">${label}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  })
}

const ICONS = {
  merchant: () => dotIcon('#0aa858', '店'),
  dest: () => dotIcon('#e8552f', '家'),
  rider: () => dotIcon('#2f6fe8', '骑'),
}

function setMarker(kind: 'merchant' | 'dest' | 'rider', pos: { lat: number; lng: number }, popup: string) {
  if (!map) return
  const gcj = wgs2gcj(pos.lat, pos.lng)
  if (markers[kind]) {
    markers[kind].setLatLng(gcj)
  } else {
    markers[kind] = L.marker(gcj, { icon: ICONS[kind]() }).addTo(map!).bindPopup(popup)
  }
}

function fitAll() {
  const pts: [number, number][] = Object.values(markers).map((m) => m.getLatLng()) as [number, number][]
  if (pts.length === 1) map?.setView(pts[0], 14)
  else if (pts.length > 1) map?.fitBounds(L.latLngBounds(pts).pad(0.3))
}

onMounted(() => {
  if (!el.value) return
  map = L.map(el.value, { zoomControl: true, attributionControl: true })
  L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=7&x={x}&y={y}&z={z}', {
    subdomains: ['1', '2', '3', '4'],
    maxZoom: 19,
    attribution: '&copy; 高德地图',
  }).addTo(map)
  map.setView(wgs2gcj(30.512, 114.43), 13)
  apply()
})

function apply() {
  if (props.merchant?.lat) setMarker('merchant', props.merchant, props.merchant.name || '取餐点')
  if (props.dest?.lat) setMarker('dest', props.dest, props.dest.text || '目的地')
  if (props.rider?.lat && props.rider?.lng) setMarker('rider', props.rider, props.rider.name || '骑手')
  fitAll()
}

watch(() => [props.merchant, props.dest, props.rider], apply, { deep: true })

onUnmounted(() => {
  map?.remove()
  map = null
})
</script>

<template>
  <div ref="el" style="width: 100%; height: 100%"></div>
</template>
