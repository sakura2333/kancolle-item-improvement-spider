'use strict'

const path = require('path')

const resolveData = (...parts) => path.join(__dirname, ...parts)

module.exports = Object.freeze({
  rootPath: __dirname,
  manifestPath: resolveData('manifest.json'),
  releasesPath: resolveData('RELEASES.json'),
  improvement: Object.freeze({
    listPath: resolveData('improvement', 'list.json'),
    detailPath: resolveData('improvement', 'detail.nedb'),
  }),
  equipment: Object.freeze({
    dropFromPath: resolveData('equipment', 'drop-from.nedb'),
    sourcesPath: resolveData('equipment', 'sources.nedb'),
    specialBonusesPath: resolveData('equipment', 'special-bonuses.nedb'),
  }),
  schemas: Object.freeze({
    improvementDetailPath: resolveData('schemas', 'improvement-detail.schema.json'),
    equipmentDropFromPath: resolveData('schemas', 'equipment-drop-from.schema.json'),
    equipmentSourcesPath: resolveData('schemas', 'equipment-sources.schema.json'),
    equipmentSpecialBonusesPath: resolveData('schemas', 'equipment-special-bonus.schema.json'),
  }),
  audit: Object.freeze({
    buildReportPath: resolveData('audit', 'build-report.json'),
  }),
  assets: Object.freeze({
    useitemPath(id) {
      return resolveData('assets', 'useitem', `${Number(id)}.png`)
    },
    equipmentPath(id) {
      return resolveData('assets', 'equip', `${Number(id)}.png`)
    },
  }),
})
