'use strict'

const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'))

for (const key of ['improvement', 'equipmentDropFrom', 'equipmentSpecialBonuses']) {
  const dataset = manifest.datasets && manifest.datasets[key]
  if (!dataset || dataset.status !== 'ok') {
    throw new Error(`dataset ${key} is not fresh: status=${dataset && dataset.status}`)
  }
  if (key === 'improvement' && dataset.collectionCompletedInRun !== true) {
    throw new Error('dataset improvement was not rebuilt by the canonical Spider in this run')
  }
  if (!Array.isArray(dataset.fetches) || dataset.fetches.length === 0) {
    throw new Error(`dataset ${key} has no source fetch audit`)
  }
  for (const fetchInfo of dataset.fetches) {
    if (fetchInfo.status !== 'fresh'
      || fetchInfo.validatedInRun !== true
      || fetchInfo.usedCacheFallback === true) {
      throw new Error(`dataset ${key} source was not freshly validated: ${fetchInfo.url}`)
    }
  }
}

console.log('source freshness checks passed')
