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
    specialBonusesPath: string
  }
  schemas: {
    improvementDetailPath: string
    equipmentDropFromPath: string
    equipmentSpecialBonusesPath: string
  }
  audit: {
    buildReportPath: string
  }
  assets: {
    useitemPath(id: number | string): string
  }
}

declare const paths: KancolleDataPaths
export = paths
