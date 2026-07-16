export interface KancolleDataPaths {
  rootPath: string
  manifestPath: string
  releasesPath: string
  improvement: {
    listPath: string
    detailPath: string
  }
  equipment: {
    dropFromPath: string
    sourcesPath: string
    specialBonusesPath: string
  }
  schemas: {
    improvementDetailPath: string
    equipmentDropFromPath: string
    equipmentSourcesPath: string
    equipmentSpecialBonusesPath: string
  }
  audit: {
    buildReportPath: string
  }
  assets: {
    useitemPath(id: number | string): string
    equipmentPath(id: number | string): string
    equipPath(id: number | string): string
  }
}

declare const paths: KancolleDataPaths
export = paths
